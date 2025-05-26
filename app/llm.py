# File: app/llm.py
import json
import google.generativeai as genai
import google.ai.generativelanguage as glm
from google.api_core import exceptions as google_api_core_exceptions
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig, Tool as GeminiSDKTool

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential
from typing import Dict, List, Optional, Union, Any, Literal, Tuple
import collections.abc # For type checking complex protobuf proxies
from enum import Enum

from app.config import config as app_main_config, GeminiSettings
from app.exceptions import TokenLimitExceeded, DRIMAIFrameworkError, LLMResponseError
from app.logger import logger
from app.schema import ROLE_TYPE, TOOL_CHOICE_TYPE, Message, ToolCall, Function, ToolChoice, Role

import base64
import uuid

ModelPurpose = Literal["general", "simple", "multimodal"]

GEMINI_ROLE_MAP = {
    "system": "user",
    "user": "user",
    "assistant": "model",
    "tool": "function"
}

def _recursive_to_json_serializable(data: Any) -> Any:
    if isinstance(data, collections.abc.Mapping):
        return {str(k): _recursive_to_json_serializable(v) for k, v in data.items()}
    elif isinstance(data, collections.abc.Sequence) and not isinstance(data, (str, bytes)):
        return [_recursive_to_json_serializable(item) for item in data]
    return data

class LLM:
    _instances: Dict[str, "LLM"] = {}

    def __new__(cls, config_name: str = "default", llm_config_override: Optional[GeminiSettings] = None):
        instance_key = config_name
        if instance_key not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[instance_key] = instance
        return cls._instances[instance_key]

    def __init__(self, config_name: str = "default", llm_config_override: Optional[GeminiSettings] = None):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.settings: GeminiSettings = llm_config_override or app_main_config.gemini

        genai.configure(api_key=self.settings.api_key)

        self.default_generation_config = GenerationConfig(
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
            top_p=self.settings.top_p,
            top_k=self.settings.top_k
        )
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }

        self.model_clients: Dict[ModelPurpose, genai.GenerativeModel] = {}
        self.fallback_models_map: Dict[str, Optional[str]] = {
            self.settings.primary_model: self.settings.fallback_primary_model,
            str(self.settings.small_model): self.settings.fallback_small_model, 
            self.settings.multimodal_model: self.settings.fallback_multimodal_model,
        }

        logger.info(f"DRIM AI LLM: Initializing Gemini models... Temperature: {self.settings.temperature}")
        try:
            self.model_clients["general"] = genai.GenerativeModel(
                model_name=self.settings.primary_model,
                generation_config=self.default_generation_config,
                safety_settings=self.safety_settings
            )
            logger.info(f"  - General purpose model: {self.settings.primary_model} initialized.")

            if self.settings.small_model:
                small_model_config = self.default_generation_config
                self.model_clients["simple"] = genai.GenerativeModel(
                    model_name=self.settings.small_model,
                    generation_config=small_model_config,
                    safety_settings=self.safety_settings
                )
                logger.info(f"  - Simple/fast model: {self.settings.small_model} initialized.")
                if str(self.settings.small_model) not in self.fallback_models_map:
                    self.fallback_models_map[str(self.settings.small_model)] = self.settings.fallback_small_model
            else:
                logger.warning("  - Simple/fast model (small_model) not configured, 'general' model will be used as fallback for 'simple' purpose.")

            self.model_clients["multimodal"] = genai.GenerativeModel(
                model_name=self.settings.multimodal_model,
                generation_config=self.default_generation_config,
                safety_settings=self.safety_settings
            )
            logger.info(f"  - Multimodal model: {self.settings.multimodal_model} initialized.")

        except Exception as e:
            logger.exception("DRIM AI LLM: Failed to initialize one or more Gemini models.")
            raise DRIMAIFrameworkError(f"Gemini model initialization failed: {e}")

        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._initialized = True

    def _get_model_client(self, purpose: ModelPurpose = "general", has_images: bool = False, model_name_override: Optional[str] = None) -> genai.GenerativeModel:
        if model_name_override:
            logger.info(f"Using model override: {model_name_override}")
            return genai.GenerativeModel(
                model_name=model_name_override,
                generation_config=self.default_generation_config, 
                safety_settings=self.safety_settings
            )

        if has_images:
            if "multimodal" in self.model_clients:
                return self.model_clients["multimodal"]
            else:
                logger.warning("Multimodal model not initialized, falling back to general for image request.")
                return self.model_clients["general"]

        if purpose == "simple":
            return self.model_clients.get("simple") or self.model_clients["general"]
        return self.model_clients["general"]

    def _convert_messages_to_gemini_format(self, messages: List[Message], for_multimodal: bool = False) -> Tuple[List[glm.Content], Optional[glm.Content]]:
        gemini_messages: List[glm.Content] = []
        system_instruction_parts: List[glm.Part] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                if isinstance(msg.content, str) and msg.content:
                    system_instruction_parts.append(glm.Part(text=msg.content))
                continue

            role = GEMINI_ROLE_MAP.get(msg.role)
            if not role:
                logger.warning(f"Unknown message role '{msg.role}' encountered. Defaulting to 'user'.")
                role = "user"

            current_parts: List[glm.Part] = []
            if isinstance(msg.content, str) and msg.content:
                current_parts.append(glm.Part(text=msg.content))
            elif isinstance(msg.content, list):
                for content_part_dict in msg.content:
                    if content_part_dict.get("type") == "text":
                        current_parts.append(glm.Part(text=content_part_dict.get("text", "")))
                    elif content_part_dict.get("type") == "image_url" and for_multimodal:
                        img_url_data = content_part_dict.get("image_url", {}).get("url", "")
                        if img_url_data.startswith("data:image/"):
                            try:
                                mime_type, b64_data_str = img_url_data.split(";",1)[0].split(":")[1], img_url_data.split(",",1)[1]
                                current_parts.append(glm.Part(inline_data=glm.Blob(data=base64.b64decode(b64_data_str), mime_type=mime_type)))
                            except Exception as e_b64:
                                logger.error(f"Error decoding base64 image_url: {e_b64}")

            if for_multimodal and msg.base64_image and not any(hasattr(p, 'inline_data') and p.inline_data for p in current_parts):
                try:
                    img_bytes = base64.b64decode(msg.base64_image)
                    mime_type = "image/jpeg" 
                    image_part = glm.Part(inline_data=glm.Blob(data=img_bytes, mime_type=mime_type))
                    current_parts.append(image_part)
                except Exception as e:
                    logger.error(f"Failed to create glm.Part from direct base64_image string: {e}")

            if msg.role == Role.TOOL:
                if not msg.tool_call_id or not msg.name:
                    logger.warning(f"Tool response message missing tool_call_id or name (function_name): {msg}")
                    if current_parts: 
                        gemini_messages.append(glm.Content(parts=current_parts, role="user")) 
                    continue

                tool_response_data: Any
                try:
                    tool_response_data = json.loads(msg.content) if msg.content and isinstance(msg.content, str) else {"result_text": str(msg.content)}
                except json.JSONDecodeError:
                    tool_response_data = {"result_text": msg.content} 

                if msg.base64_image and for_multimodal:
                    if not isinstance(tool_response_data, dict): tool_response_data = {"result_text": str(tool_response_data)}
                    tool_response_data["base64_image_from_tool"] = msg.base64_image

                gemini_messages.append(glm.Content(parts=[
                    glm.Part(function_response=glm.FunctionResponse(name=msg.name, response=tool_response_data))
                ]))
                continue

            if msg.role == Role.ASSISTANT and msg.tool_calls:
                assistant_glm_parts: List[glm.Part] = []
                if msg.content and isinstance(msg.content, str): 
                    assistant_glm_parts.append(glm.Part(text=msg.content))

                for tc in msg.tool_calls:
                    try:
                        args_dict = json.loads(tc.function.arguments or "{}")
                        assistant_glm_parts.append(glm.Part(function_call=glm.FunctionCall(name=tc.function.name, args=args_dict)))
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON arguments for tool call {tc.function.name}: {tc.function.arguments}")
                
                if assistant_glm_parts: 
                    gemini_messages.append(glm.Content(parts=assistant_glm_parts, role=role))
                continue

            if current_parts:
                 gemini_messages.append(glm.Content(parts=current_parts, role=role))

        final_system_instruction_obj = glm.Content(parts=system_instruction_parts, role="user") if system_instruction_parts else None
        return gemini_messages, final_system_instruction_obj

    async def _execute_gemini_call(
        self,
        model_client: genai.GenerativeModel,
        call_args: Dict[str, Any],
        stream: bool = False
    ) -> Union[genai.GenerativeModel.generate_content_async, genai.types.GenerateContentResponse]: # type: ignore
        if stream:
            return await model_client.generate_content_async(**call_args, stream=True)
        else:
            return await model_client.generate_content_async(**call_args)

    async def ask(
        self,
        messages: List[Message],
        system_msgs: Optional[List[Message]] = None,
        stream: bool = False,
        model_purpose: ModelPurpose = "general",
        generation_config_override: Optional[GenerationConfig] = None,
    ) -> str:
        all_input_messages = (system_msgs or []) + messages
        has_images = any(msg.base64_image or (isinstance(msg.content, list) and any(p.get("type")=="image_url" for p in msg.content)) for msg in all_input_messages)
        
        active_model_client = self._get_model_client(model_purpose, has_images)
        current_model_name = active_model_client.model_name
        logger.info(f"DRIM AI LLM ({current_model_name}): Processing 'ask' request (Stream: {stream}).")

        main_dialogue_gemini_msgs, system_instruction_obj = self._convert_messages_to_gemini_format(
            all_input_messages,
            for_multimodal=has_images
        )

        final_contents_for_api = main_dialogue_gemini_msgs
        if system_instruction_obj:
            final_contents_for_api = [system_instruction_obj] + main_dialogue_gemini_msgs
            logger.debug("Prepending system instruction to conversation history for API call in 'ask'.")

        if not final_contents_for_api:
             logger.warning("No messages or system instruction to send to LLM for 'ask'.")
             return "Error: No content to process."

        current_gen_config = generation_config_override or self.default_generation_config
        
        api_call_args = {
            "contents": final_contents_for_api,
            "generation_config": current_gen_config
        }

        response: Union[genai.GenerativeModel.generate_content_async, genai.types.GenerateContentResponse] # type: ignore
        try:
            response = await self._execute_gemini_call(active_model_client, api_call_args, stream=stream)
        except google_api_core_exceptions.ResourceExhausted as re_ex:
            logger.warning(f"DRIM AI LLM ({current_model_name}): Rate limit hit for 'ask'. Attempting fallback. Error: {re_ex}")
            fallback_model_name = self.fallback_models_map.get(current_model_name)
            if fallback_model_name and fallback_model_name != current_model_name:
                logger.info(f"DRIM AI LLM: Falling back to {fallback_model_name} for 'ask' request.")
                fallback_model_client = self._get_model_client(model_name_override=fallback_model_name) 
                try:
                    response = await self._execute_gemini_call(fallback_model_client, api_call_args, stream=stream)
                    current_model_name = fallback_model_name 
                except google_api_core_exceptions.ResourceExhausted as re_ex_fallback:
                    logger.error(f"DRIM AI LLM ({fallback_model_name}): Rate limit hit on fallback as well for 'ask'. Error: {re_ex_fallback}")
                    raise DRIMAIFrameworkError(f"Gemini API rate limit on primary and fallback: {re_ex_fallback}") from re_ex_fallback
                except Exception as e_fallback:
                    logger.exception(f"DRIM AI LLM ({fallback_model_name}): Error during 'ask' fallback call: {e_fallback}")
                    raise DRIMAIFrameworkError(f"Gemini API Error on fallback: {str(e_fallback)}") from e_fallback
            else:
                logger.error(f"DRIM AI LLM ({current_model_name}): Rate limit hit, but no different fallback model configured.")
                raise DRIMAIFrameworkError(f"Gemini API rate limit: {re_ex}") from re_ex
        except genai.types.BlockedPromptException as bpe: # type: ignore
            logger.error(f"DRIM AI LLM ({current_model_name}) prompt blocked in 'ask': {bpe}. Safety ratings: {bpe.safety_ratings if hasattr(bpe, 'safety_ratings') else 'N/A'}") # type: ignore
            raise LLMResponseError(f"Request blocked by content safety filter: {getattr(bpe, 'block_reason', 'Unknown')}") from bpe # type: ignore
        except genai.types.StopCandidateException as sce: 
            logger.error(f"DRIM AI LLM ({current_model_name}) generation stopped in 'ask': {sce}. Finish reason: {sce.finish_reason if hasattr(sce, 'finish_reason') else 'N/A'}") # type: ignore
            partial_text = ""
            if sce.candidate and sce.candidate.content and hasattr(sce.candidate.content, 'parts'): # type: ignore
                 partial_text = "".join(p.text for p in sce.candidate.content.parts if hasattr(p, 'text') and p.text) # type: ignore
            raise LLMResponseError(f"Content generation stopped. Reason: {getattr(sce, 'finish_reason', 'Unknown')}. Partial: {partial_text}") from sce # type: ignore
        except google_api_core_exceptions.GoogleAPIError as gape: 
            logger.exception(f"DRIM AI LLM ({current_model_name}) GoogleAPIError in 'ask': {gape}")
            raise DRIMAIFrameworkError(f"Gemini GoogleAPIError: {str(gape)}") from gape
        except Exception as e: 
            logger.exception(f"DRIM AI LLM ({current_model_name}) error in 'ask': {e}")
            raise DRIMAIFrameworkError(f"Gemini API Error: {str(e)}") from e

        if stream:
            full_response_text = ""
            async for chunk in response: 
                if chunk.parts and hasattr(chunk.parts[0], 'text') and chunk.parts[0].text:
                    text_part = chunk.parts[0].text
                    print(text_part, end="", flush=True)
                    full_response_text += text_part
            print()
            return full_response_text
        else:
            # Ensure response is not the unresolved async generator type here
            if not isinstance(response, genai.types.GenerateContentResponse):
                # This case should ideally not be hit if stream=False, but as a safeguard
                logger.error(f"DRIM AI LLM ({current_model_name}): Unexpected response type for non-streamed 'ask'. Type: {type(response)}")
                return "Error: Unexpected response type from LLM."

            self._update_token_count_from_usage_metadata(getattr(response, 'usage_metadata', None))
            response_text_parts = []
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part_obj in response.candidates[0].content.parts:
                    if hasattr(part_obj, 'text') and part_obj.text:
                        response_text_parts.append(part_obj.text)
            elif hasattr(response, 'parts') and response.parts: 
                 for part_obj in response.parts: # type: ignore
                    if hasattr(part_obj, 'text') and part_obj.text:
                        response_text_parts.append(part_obj.text)

            if response_text_parts:
                return "".join(response_text_parts)
            logger.warning(f"DRIM AI LLM ({current_model_name}): No text parts in 'ask' response. Candidates: {response.candidates if hasattr(response, 'candidates') else 'N/A'}")
            return "Error: No valid response content from Gemini."


    async def ask_tool(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO, 
        system_msgs: Optional[List[Message]] = None,
        model_purpose: ModelPurpose = "general",
        generation_config_override: Optional[GenerationConfig] = None,
    ) -> Message:
        all_input_messages = (system_msgs or []) + messages
        has_images = any(msg.base64_image or (isinstance(msg.content, list) and any(p.get("type")=="image_url" for p in msg.content)) for msg in all_input_messages)
        
        active_model_client = self._get_model_client(model_purpose, has_images)
        current_model_name = active_model_client.model_name
        logger.info(f"DRIM AI LLM ({current_model_name}): Processing 'ask_tool' request. Tool choice: {tool_choice}.")

        main_dialogue_gemini_msgs, system_instruction_obj = self._convert_messages_to_gemini_format(
            all_input_messages,
            for_multimodal=has_images
        )

        final_contents_for_api = main_dialogue_gemini_msgs
        if system_instruction_obj:
            final_contents_for_api = [system_instruction_obj] + main_dialogue_gemini_msgs
            logger.debug("Prepending system instruction to conversation history for API call in 'ask_tool'.")

        if not final_contents_for_api:
             logger.warning("No messages or system instruction to send to LLM for 'ask_tool'.")
             return Message.assistant_message(content="Error: No content to process for tool call.")

        gemini_sdk_tools_list: Optional[List[GeminiSDKTool]] = None
        if tools:
            try:
                gemini_sdk_tools_list = [GeminiSDKTool(function_declarations=tools)] # type: ignore
            except Exception as e:
                logger.error(f"Error creating GeminiSDKTool from tools schema: {e}. Tools: {tools}")
                raise DRIMAIFrameworkError(f"Invalid tool schema for Gemini: {e}") from e

        gemini_tool_config_dict: Optional[Dict[str, Any]] = None 
        if gemini_sdk_tools_list:
            mode_map = {
                ToolChoice.NONE.value: "NONE",
                ToolChoice.AUTO.value: "AUTO",
                ToolChoice.REQUIRED.value: "ANY", 
            }
            
            processed_tool_choice_str: Optional[str] = None
            is_specific_function_dict_choice = False

            if isinstance(tool_choice, ToolChoice): 
                processed_tool_choice_str = tool_choice.value
            elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                func_details = tool_choice.get("function")
                if isinstance(func_details, dict) and func_details.get("name"):
                    processed_tool_choice_str = func_details["name"]
                    is_specific_function_dict_choice = True
                    logger.info(f"Specific function name for tool_choice extracted: {processed_tool_choice_str}")
                else: # Malformed dict
                    processed_tool_choice_str = str(tool_choice) # Fallback to string representation
            else: 
                processed_tool_choice_str = str(tool_choice)


            if processed_tool_choice_str in mode_map: # e.g. "none", "auto", "required"
                current_mode = mode_map[processed_tool_choice_str]
                gemini_tool_config_dict = {"function_calling_config": {"mode": current_mode}}
                if current_mode == "ANY" and \
                   gemini_sdk_tools_list and \
                   gemini_sdk_tools_list[0].function_declarations and \
                   len(gemini_sdk_tools_list[0].function_declarations) == 1:
                    the_only_tool_name = gemini_sdk_tools_list[0].function_declarations[0].name
                    if "function_calling_config" not in gemini_tool_config_dict : 
                        gemini_tool_config_dict = {"function_calling_config":{}}
                    gemini_tool_config_dict["function_calling_config"]["allowed_function_names"] = [the_only_tool_name]
                    logger.info(f"ToolChoice.REQUIRED used with single available tool '{the_only_tool_name}', explicitly setting allowed_function_names for Gemini.")
            elif processed_tool_choice_str: # A specific function name was provided (either directly as str or extracted from dict)
                gemini_tool_config_dict = {
                    "function_calling_config": {
                        "mode": "ANY", 
                        "allowed_function_names": [processed_tool_choice_str],
                    }
                }
                logger.info(f"Forcing specific tool: {processed_tool_choice_str} with mode ANY.")
            else: 
                logger.warning(f"Invalid or empty processed_tool_choice_str '{processed_tool_choice_str}' after processing, defaulting to AUTO mode for tool config.")
                gemini_tool_config_dict = {"function_calling_config": {"mode": "AUTO"}}
        
        current_gen_config = generation_config_override or self.default_generation_config
        
        api_call_args = {
            "contents": final_contents_for_api,
            "tools": gemini_sdk_tools_list,
            "tool_config": gemini_tool_config_dict, 
            "generation_config": current_gen_config
        }

        response: genai.types.GenerateContentResponse
        try:
            response = await self._execute_gemini_call(active_model_client, api_call_args, stream=False) # type: ignore
        except google_api_core_exceptions.ResourceExhausted as re_ex:
            logger.warning(f"DRIM AI LLM ({current_model_name}): Rate limit hit for 'ask_tool'. Attempting fallback. Error: {re_ex}")
            fallback_model_name = self.fallback_models_map.get(current_model_name)
            if fallback_model_name and fallback_model_name != current_model_name:
                logger.info(f"DRIM AI LLM: Falling back to {fallback_model_name} for 'ask_tool' request.")
                fallback_model_client = self._get_model_client(model_name_override=fallback_model_name)
                try:
                    response = await self._execute_gemini_call(fallback_model_client, api_call_args, stream=False) # type: ignore
                    current_model_name = fallback_model_name 
                except google_api_core_exceptions.ResourceExhausted as re_ex_fallback:
                    logger.error(f"DRIM AI LLM ({fallback_model_name}): Rate limit hit on fallback as well for 'ask_tool'. Error: {re_ex_fallback}")
                    raise DRIMAIFrameworkError(f"Gemini API rate limit on primary and fallback (ask_tool): {re_ex_fallback}") from re_ex_fallback
                except Exception as e_fallback:
                    logger.exception(f"DRIM AI LLM ({fallback_model_name}): Error during 'ask_tool' fallback call: {e_fallback}")
                    raise DRIMAIFrameworkError(f"Gemini API Error on fallback (ask_tool): {str(e_fallback)}") from e_fallback
            else:
                logger.error(f"DRIM AI LLM ({current_model_name}): Rate limit hit for 'ask_tool', but no different fallback model configured.")
                raise DRIMAIFrameworkError(f"Gemini API rate limit (ask_tool): {re_ex}") from re_ex
        except genai.types.BlockedPromptException as bpe: # type: ignore
            logger.error(f"DRIM AI LLM ({current_model_name}) prompt blocked during tool call: {bpe}. Safety ratings: {bpe.safety_ratings if hasattr(bpe, 'safety_ratings') else 'N/A'}") # type: ignore
            raise LLMResponseError(f"Tool request blocked by content safety filter: {getattr(bpe, 'block_reason', 'Unknown')}") from bpe # type: ignore
        except genai.types.StopCandidateException as sce: 
            logger.error(f"DRIM AI LLM ({current_model_name}) generation stopped during tool call: {sce}. Finish reason: {sce.finish_reason if hasattr(sce, 'finish_reason') else 'N/A'}") # type: ignore
            partial_text = ""
            if sce.candidate and sce.candidate.content and hasattr(sce.candidate.content, 'parts'): # type: ignore
                 partial_text = "".join(p.text for p in sce.candidate.content.parts if hasattr(p, 'text') and p.text) # type: ignore
            raise LLMResponseError(f"Tool call generation stopped. Reason: {getattr(sce, 'finish_reason', 'Unknown')}. Partial: {partial_text}") from sce # type: ignore
        except google_api_core_exceptions.GoogleAPIError as gape:
            logger.exception(f"DRIM AI LLM ({current_model_name}) GoogleAPIError in 'ask_tool': {gape}")
            raise DRIMAIFrameworkError(f"Gemini GoogleAPIError during tool call: {str(gape)}") from gape
        except TypeError as te: 
            logger.exception(f"DRIM AI LLM ({current_model_name}) TypeError in 'ask_tool': {te}")
            raise DRIMAIFrameworkError(f"Gemini API call failed due to TypeError (often unexpected kwarg or schema issue): {str(te)}") from te
        except Exception as e:
            logger.exception(f"DRIM AI LLM ({current_model_name}) error in 'ask_tool': {e}")
            raise DRIMAIFrameworkError(f"Gemini API Error during tool call: {str(e)}") from e

        self._update_token_count_from_usage_metadata(getattr(response, 'usage_metadata', None))
        response_message_content: Optional[str] = None
        response_tool_calls: List[ToolCall] = []

        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content and candidate.content.parts:
            for part_obj in candidate.content.parts:
                if hasattr(part_obj, 'text') and part_obj.text:
                    response_message_content = (response_message_content or "") + part_obj.text
                elif hasattr(part_obj, 'function_call') and part_obj.function_call:
                    fc = part_obj.function_call
                    serializable_args = {}
                    if fc.args:
                        try:
                            naive_dict_args = dict(fc.args)
                            serializable_args = _recursive_to_json_serializable(naive_dict_args)
                        except Exception as e_conv:
                            logger.error(f"Error converting FunctionCall.args for {fc.name}: {e_conv}. Args: {fc.args}")
                            serializable_args = dict(fc.args) 

                    arguments_json_string = json.dumps(serializable_args)
                    response_tool_calls.append(
                        ToolCall(
                            id=f"call_{fc.name}_{uuid.uuid4().hex[:8]}",
                            type="function",
                            function=Function(name=fc.name, arguments=arguments_json_string)
                        )
                    )

        is_required_enum = isinstance(tool_choice, ToolChoice) and tool_choice == ToolChoice.REQUIRED
        # Check if tool_choice was a specific function name (either string or extracted from dict)
        is_required_specific_tool = (isinstance(processed_tool_choice_str, str) and processed_tool_choice_str not in mode_map)


        if (is_required_enum or is_required_specific_tool) and not response_tool_calls:
            # MODIFIED: Robust access to logging information from the Python dict gemini_tool_config_dict
            fcc_part_from_dict = None
            if gemini_tool_config_dict and isinstance(gemini_tool_config_dict.get('function_calling_config'), dict):
                fcc_part_from_dict = gemini_tool_config_dict['function_calling_config']

            mode_for_log = "NOT_CONFIGURED"
            allowed_names_for_log = "ALL_TOOLS_IN_SCOPE" 

            if isinstance(fcc_part_from_dict, dict): 
                mode_for_log = fcc_part_from_dict.get('mode', 'MODE_UNKNOWN_IN_DICT')
                allowed_names_list = fcc_part_from_dict.get('allowed_function_names')
                if allowed_names_list:
                    allowed_names_for_log = str(allowed_names_list)
            
            if allowed_names_for_log == "ALL_TOOLS_IN_SCOPE" and mode_for_log == "ANY":
                if tool_choice == ToolChoice.REQUIRED: 
                     if gemini_sdk_tools_list and \
                        gemini_sdk_tools_list[0].function_declarations and \
                        len(gemini_sdk_tools_list[0].function_declarations) == 1: 
                         allowed_names_for_log = str([gemini_sdk_tools_list[0].function_declarations[0].name])
                     elif gemini_sdk_tools_list and gemini_sdk_tools_list[0].function_declarations: # Multiple tools in scope for general "ANY"
                         allowed_names_for_log = str([fd.name for fd in gemini_sdk_tools_list[0].function_declarations])
                # If tool_choice was originally a dict pointing to a specific function, processed_tool_choice_str holds its name
                elif is_specific_function_dict_choice and processed_tool_choice_str:
                    allowed_names_for_log = str([processed_tool_choice_str])
                elif isinstance(tool_choice, str) and tool_choice not in mode_map : # If tool_choice was a direct string function name
                    allowed_names_for_log = str([tool_choice])


            log_msg_parts = [f"Mode: {mode_for_log}"]
            if allowed_names_for_log != "ALL_TOOLS_IN_SCOPE":
                log_msg_parts.append(f"Allowed: {allowed_names_for_log}")
            
            final_log_mode_info = ", ".join(log_msg_parts)
            logger.warning(f"DRIM AI LLM ({current_model_name}): Tool call was required ({final_log_mode_info}) but none made by LLM.")
            return Message(role=Role.ASSISTANT, content="I was required to use a tool for this step, but I could not identify a suitable one or did not receive instructions/ability to use one from the LLM. Please clarify or provide more context.")

        return Message(role=Role.ASSISTANT, content=response_message_content, tool_calls=response_tool_calls if response_tool_calls else None)

    async def count_tokens(self, text_or_contents: Union[str, List[glm.Content], glm.Content], model_purpose: ModelPurpose = "general") -> int:
        is_multimodal_content = False
        if isinstance(text_or_contents, list):
            is_multimodal_content = any(isinstance(c, glm.Content) and any(hasattr(p, 'inline_data') and p.inline_data for p in c.parts) for c in text_or_contents)
        elif isinstance(text_or_contents, glm.Content):
            is_multimodal_content = any(hasattr(p, 'inline_data') and p.inline_data for p in text_or_contents.parts)

        client_for_counting = self._get_model_client(purpose=model_purpose, has_images=is_multimodal_content)
        if not text_or_contents : return 0
        try:
            token_count_response = await client_for_counting.count_tokens_async(text_or_contents)
            return token_count_response.total_tokens
        except Exception as e:
            logger.warning(f"DRIM AI LLM: Could not count tokens via API for model {client_for_counting.model_name}: {e}. Estimating.")
            if isinstance(text_or_contents, str): return len(text_or_contents) // 4
            total_chars = 0
            if isinstance(text_or_contents, list):
                for content_item in text_or_contents:
                    if hasattr(content_item, 'parts'):
                        for part in content_item.parts:
                            if hasattr(part, 'text'): total_chars += len(part.text or "")
            elif isinstance(text_or_contents, glm.Content) and hasattr(text_or_contents, 'parts'):
                for part in text_or_contents.parts:
                     if hasattr(part, 'text'): total_chars += len(part.text or "")
            return total_chars // 4

    async def count_message_tokens(self, messages: List[Message], model_purpose: ModelPurpose = "general") -> int:
        has_images = any(msg.base64_image or (isinstance(msg.content, list) and any(p.get("type")=="image_url" for p in msg.content)) for msg in messages)

        gemini_formatted_dialogue, system_instruction_obj = self._convert_messages_to_gemini_format(messages, for_multimodal=has_images)

        contents_to_count: List[glm.Content] = []
        if system_instruction_obj:
            contents_to_count.append(system_instruction_obj)
        contents_to_count.extend(gemini_formatted_dialogue)

        if not contents_to_count: return 0

        effective_purpose = "multimodal" if has_images else model_purpose
        return await self.count_tokens(contents_to_count, model_purpose=effective_purpose)

    def _update_token_count(self, input_tokens: int = 0, completion_tokens: int = 0) -> None:
        self._total_input_tokens += input_tokens
        self._total_output_tokens += completion_tokens

    def _update_token_count_from_usage_metadata(self, usage_metadata: Optional[glm.GenerateContentResponse.UsageMetadata]):
        if usage_metadata:
            prompt_tokens = usage_metadata.prompt_token_count
            candidates_tokens = getattr(usage_metadata, 'candidates_token_count', 0)
            if candidates_tokens == 0 and hasattr(usage_metadata, 'total_token_count') and usage_metadata.total_token_count > prompt_tokens:
                candidates_tokens = usage_metadata.total_token_count - prompt_tokens

            self._update_token_count(input_tokens=prompt_tokens, completion_tokens=candidates_tokens)
            logger.info(f"DRIM AI Token usage from metadata: Input={prompt_tokens}, Completion={candidates_tokens}. "
                        f"Cumulative Input={self._total_input_tokens}, Cumulative Completion={self._total_output_tokens}")

    def check_token_limit(self, input_tokens: int, model_context_window: int = 32768) -> bool: 
        if input_tokens + self.settings.max_output_tokens > model_context_window :
             logger.warning(f"Potential token limit issue: Input ({input_tokens}) + Max Output ({self.settings.max_output_tokens}) > Context Window ({model_context_window})")
        if input_tokens > model_context_window: return False
        return True

    def get_limit_error_message(self, input_tokens: int, model_context_window: int = 32768) -> str:
        return f"Request with {input_tokens} input tokens (+ max_output_tokens: {self.settings.max_output_tokens}) may exceed model's context window of {model_context_window} tokens."