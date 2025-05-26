// DRIM AI Chart Visualization Script (chartVisualize.ts)
// Original source from OpenManus PDF [Source: 525-570]
// DRIM AI ADAPTATION NOTES:
// This script is called by DataVisualization.py and receives LLM configuration.
// For Gemini integration, especially for VMind's LLM-dependent features like `getInsights`
// or LLM-driven `generateChart` strategies, direct SDK usage is recommended.
// See the section "DRIM AI: VMind Initialization with LLM" for detailed comments.

import Canvas from "canvas";
import path from "path";
import fs from "fs";
import VMind, { ChartType, DataTable, Model as VMindModel } from "@visactor/vmind"; // Added VMindModel
import VChart from "@visactor/vchart";
import { isString } from "@visactor/vutils";

// DRIM AI: If using Gemini SDK, import it here
import { GoogleGenerativeAI, HarmCategory, HarmBlockThreshold } from "@google/generative-ai";

enum AlgorithmType { // [Source: 527]
  OverallTrending = "overallTrend", AbnormalTrend = "abnormalTrend",
  PearsonCorrelation = "pearsonCorrelation", SpearmanCorrelation = "spearmanCorrelation",
  ExtremeValue = "extremeValue", MajorityValue = "majorityValue",
  StatisticsAbnormal = "statisticsAbnormal", StatisticsBase = "statisticsBase",
  DbscanOutlier = "dbscanOutlier", LOFOutlier = "lofOutlier",
  TurningPoint = "turningPoint", PageHinkley = "pageHinkley",
  DifferenceOutlier = "differenceOutlier", Volatility = "volatility",
}

const getBase64 = async (spec: any, width?: number, height?: number) => { // [Source: 528]
  spec.animation = false; width && (spec.width = width); height && (spec.height = height);
  const cs = new VChart(spec, { mode: "node", modeParams: Canvas, animation: false, dpr: 2 }); // [Source: 529]
  await cs.renderAsync(); const buffer = await cs.getImageBuffer(); return buffer; // [Source: 529, 530]
};

const serializeSpec = (spec: any) => { /* ... (same as before from [Source: 530]) ... */
  return JSON.stringify(spec, (key, value) => {
    if (typeof value === "function") {
      const funcStr = value.toString().replace(/(\r\n|\n|\r)/gm, "").replace(/\s+/g, " ");
      return `__FUNCTION__${funcStr}`;
    }
    return value;
  });
};

async function getHtmlVChart(spec: any, width?: number, height?: number) { /* ... (same as before from [Source: 531-534], title updated) ... */
  return `<!DOCTYPE html>
<html>
<head>
  <title>VChart Example for DRIM AI</title>
  <script src="https://unpkg.com/@visactor/vchart/build/index.min.js"></script>
</head>
<body>
  <div id="chart-container" style="width: ${width ? `${width}px` : "100%"}; height: ${height ? `${height}px` : "100%"};"></div>
  <script>
  function parseSpec(stringSpec) {
    return JSON.parse(stringSpec, (k, v) => {
      if (typeof v === 'string' && v.startsWith('__FUNCTION__')) {
        const funcBody = v.slice(12);
        try { return new Function('return (' + funcBody + ')')(); } catch(e) { console.error('Function parsing failed:', e); return () => {}; }
      }
      return v;
    });
  }
  const spec = parseSpec(\`${serializeSpec(spec)}\`);
  const chart = new VChart.VChart(spec, { dom: 'chart-container' });
  chart.renderSync();
  </script>
</body>
</html>
`;
}

function getSavedPathName( directory: string, fileName: string, outputType: "html" | "png" | "json" | "md", isUpdate: boolean = false ): string { /* ... (same as before, using "visualization_outputs_drim_ai" subfolder) ... */
  let newFileName = fileName;
  const visualizationDir = path.join(directory, "visualization_outputs_drim_ai");
  if (!fs.existsSync(visualizationDir)) {
    fs.mkdirSync(visualizationDir, { recursive: true });
  }
  while (!isUpdate && fs.existsSync(path.join(visualizationDir, `${newFileName}.${outputType}`))) {
    newFileName += "_new";
  }
  return path.join(visualizationDir, `${newFileName}.${outputType}`);
}

const readStdin = (): Promise<string> => { /* ... (same as before from [Source: 536]) ... */
  return new Promise((resolve) => {
    let input = ""; process.stdin.setEncoding("utf-8");
    process.stdin.on("data", (chunk) => (input += chunk));
    process.stdin.on("end", () => resolve(input));
  });
};

const setInsightTemplate = ( insightFilePath: string, chartTitle: string, insightsContent: string[] ): { insight_path?: string; insight_md?: string } => { /* ... (same as before from [Source: 537-539]) ... */
  let markdownResult = "";
  if (insightsContent.length) {
    markdownResult += `## Insights for: ${chartTitle}`;
    insightsContent.forEach((insight, index) => { markdownResult += `\n${index + 1}. ${insight}`; });
  }
  if (markdownResult) {
    fs.writeFileSync(insightFilePath, markdownResult, "utf-8");
    return { insight_path: insightFilePath, insight_md: markdownResult };
  }
  return {};
};

async function saveChartRes(options: { spec: any; directory: string; outputType: "png" | "html"; fileName: string; width?: number; height?: number; isUpdate?: boolean; }): Promise<string> { /* ... (same as before from [Source: 540-543]) ... */
  const { directory, fileName, spec, outputType, width, height, isUpdate } = options;
  const specPath = getSavedPathName(directory, fileName, "json", isUpdate);
  fs.writeFileSync(specPath, JSON.stringify(spec, null, 2));
  const chartSavedPath = getSavedPathName(directory, fileName, outputType, isUpdate);
  if (outputType === "png") {
    const base64Buffer = await getBase64(spec, width, height); fs.writeFileSync(chartSavedPath, base64Buffer);
  } else {
    const htmlContent = await getHtmlVChart(spec, width, height); fs.writeFileSync(chartSavedPath, htmlContent, "utf-8");
  }
  return chartSavedPath;
}

async function generateChart( vmind: VMind, options: { dataset_json_str: string | DataTable; userPrompt: string; directory: string; outputType: "png" | "html"; fileName: string; width?: number; height?: number; language?: "en" | "zh"; }): Promise<{ chart_path?: string; error?: string; insight_path?: string; insight_md?: string; }> { /* ... (same as before, from [Source: 544-557]) ... */
  let response: { chart_path?: string; error?: string; insight_path?: string; insight_md?: string; } = {};
  const { dataset_json_str, userPrompt, directory, width, height, outputType, fileName, language, } = options;
  try {
    const parsedDataset = isString(dataset_json_str) ? JSON.parse(dataset_json_str) : dataset_json_str;
    const { spec, error: vmindChartError, chartType } = await vmind.generateChart( userPrompt, undefined, parsedDataset, { enableDataQuery: false, theme: "light" } );
    if (vmindChartError || !spec) { response.error = `VMind chart generation error: ${vmindChartError || "Spec was empty!"}`; return response; }
    spec.title = { text: userPrompt, visible: true };
    response.chart_path = await saveChartRes({ directory, spec, width, height, fileName, outputType });
    const insights: any[] = [];
    if (chartType && [ChartType.BarChart, ChartType.LineChart, ChartType.AreaChart, ChartType.ScatterPlot, ChartType.DualAxisChart].includes(chartType)) {
      const { insights: vmindInsights, error: insightError } = await vmind.getInsights(spec, { maxNum: 6, algorithms: Object.values(AlgorithmType) as any, usePolish: false, language: language === "en" ? "english" : "chinese" });
      if (insightError) { console.warn("VMind getInsights error:", insightError); } else if (vmindInsights) { insights.push(...vmindInsights); }
    }
    const insightsTextContent = insights.map((insight) => insight.textContent?.plainText).filter((text) => !!text) as string[];
    spec.insights = insights;
    const specPath = getSavedPathName(directory, fileName, "json", true);
    fs.writeFileSync(specPath, JSON.stringify(spec, null, 2));
    if (insightsTextContent.length > 0) {
      const insightMarkdownPath = getSavedPathName(directory, fileName, "md");
      const insightSaveResult = setInsightTemplate(insightMarkdownPath, userPrompt, insightsTextContent);
      response.insight_path = insightSaveResult.insight_path; response.insight_md = insightSaveResult.insight_md;
    }
  } catch (err: any) { console.error("Error in generateChart (chartVisualize.ts):", err); response.error = err.toString();
  } finally { return response; }
}

async function updateChartWithInsight( vmind: VMind, options: { directory: string; outputType: "png" | "html"; fileName: string; insightsId: number[]; }): Promise<{ error?: string; chart_path?: string }> { /* ... (same as before from [Source: 557-563]) ... */
  const { directory, outputType, fileName, insightsId } = options;
  let response: { error?: string; chart_path?: string } = {};
  try {
    const specPath = getSavedPathName(directory, fileName, "json", true);
    if (!fs.existsSync(specPath)) { throw new Error(`Spec file not found for chart '${fileName}' at ${specPath}`); }
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    const availableInsights = spec.insights || [];
    const selectedInsights = availableInsights.filter( (_insight: any, index: number) => insightsId.includes(index + 1) );
    if (selectedInsights.length === 0) { throw new Error(`No insights selected or found for IDs: ${insightsId.join(', ')} from available insights for chart '${fileName}'.`); }
    const { newSpec, error: vmindUpdateError } = await vmind.updateSpecByInsights(spec, selectedInsights);
    if (vmindUpdateError || !newSpec) { throw new Error(`VMind updateSpecByInsights error: ${vmindUpdateError || "newSpec was empty"}`); }
    response.chart_path = await saveChartRes({ spec: newSpec, directory, outputType, fileName, isUpdate: true, width: spec.width, height: spec.height, });
  } catch (err: any) { console.error("Error in updateChartWithInsight (chartVisualize.ts):", err); response.error = err.toString();
  } finally { return response; }
}


// --- Main execution logic ---
async function main() {
  const inputJsonStr = await readStdin();
  const inputData = JSON.parse(inputJsonStr);
  let result;

  const {
    llm_config, // Expected: { service_provider, api_key, model }
    width, dataset_json_str = null, height, directory,
    user_prompt: userPrompt = null, output_type: outputType = "png",
    file_name: fileName, task_type: taskType = "visualization",
    insights_id: insightsId = [], language = "en",
  } = inputData;

  let vmindInstance: VMind;

  // --- DRIM AI: VMind Initialization with LLM ---
  if (llm_config && llm_config.service_provider === "gemini" && llm_config.api_key && llm_config.model) {
    console.warn("DRIM AI (chartVisualize.ts): Attempting to configure VMind for Gemini.");
    console.warn("This may require VMind to support custom LLM request functions or for you to adapt this script to use the Gemini Node.js SDK directly with VMind's non-LLM chart generation capabilities if its direct LLM features are not compatible.");

    // Strategy A: Attempt direct configuration (HIGHLY DEPENDENT ON VMIND'S FLEXIBILITY)
    // This strategy assumes VMind can work with a generic HTTP endpoint and specific headers.
    // The Gemini REST API endpoint structure is:
    // POST https://generativelanguage.googleapis.com/v1beta/models/{model}:{method}?key={apiKey}
    // For text generation, method is generateContent. For function calling, it's the same.
    const geminiModelForVMind = llm_config.model.startsWith('models/') ? llm_config.model.substring(7) : llm_config.model;
    const geminiApiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${geminiModelForVMind}:generateContent`; // Removed ?key from here

    try {
      vmindInstance = new VMind({
        url: geminiApiUrl, // VMind will append ?key=API_KEY if its internal request logic is like that, or use headers
        model: llm_config.model, // VMind might pass this in the request body
        headers: {
          // For Gemini, the API key is usually passed as `?key=YOUR_API_KEY` in the URL
          // or as an `x-goog-api-key` header.
          // VMind's `headers` option might just pass these through.
          // The `api-key` and `Authorization` headers are more OpenAI-style.
          "x-goog-api-key": llm_config.api_key, // Preferred for Gemini if VMind passes it
          "Content-Type": "application/json",
          // Remove OpenAI specific headers if VMind doesn't intelligently ignore them based on URL
        },
        // maxRetries: 3, // Optional: if VMind supports it
        // timeout: 20000, // Optional: ms
        // customRequestFunc: async (prompt, userMessage, options) => {
        //   // This is where you would use the @google/generative-ai SDK
        //   // console.log("Using customRequestFunc for Gemini with VMind");
        //   // const genAI = new GoogleGenerativeAI(llm_config.api_key);
        //   // const model = genAI.getGenerativeModel({ model: llm_config.model });
        //   // const geminiPrompt = `${prompt}\n${userMessage}`; // Combine as needed
        //   // const geminiResult = await model.generateContent(geminiPrompt);
        //   // const responseText = geminiResult.response.text();
        //   // return { message: { जवाब: responseText } }; // Adapt to VMind's expected LLMResponse structure
        //   throw new Error("Gemini customRequestFunc not fully implemented. Direct HTTP config attempted.");
        // }
      });
      console.log(`DRIM AI (chartVisualize.ts): VMind initialized for Gemini (model: ${llm_config.model}) using direct HTTP config (URL: ${geminiApiUrl}). LLM-dependent features' success relies on VMind's compatibility.`);
    } catch (e: any) {
        console.error("DRIM AI (chartVisualize.ts): Error initializing VMind with Gemini direct config: ", e.message);
        console.warn("DRIM AI (chartVisualize.ts): Falling back to VMind without LLM capabilities for Gemini.");
        vmindInstance = new VMind({}); // Fallback
    }

  } else if (llm_config && llm_config.base_url && llm_config.model && llm_config.api_key) {
    // Fallback for OpenAI-like configuration if service_provider isn't "gemini"
    console.log(`DRIM AI (chartVisualize.ts): Initializing VMind with OpenAI-like config: ${llm_config.base_url}`);
    vmindInstance = new VMind({
      url: `${llm_config.base_url}/chat/completions`, // This is OpenAI style
      model: llm_config.model as VMindModel, // Cast if VMindModel has specific values
      headers: { "api-key": llm_config.api_key, Authorization: `Bearer ${llm_config.api_key}` },
    });
  } else {
    console.warn("DRIM AI (chartVisualize.ts): LLM config missing or incomplete. Initializing VMind without LLM features.");
    vmindInstance = new VMind({}); // Initialize without LLM if config is insufficient
  }
  // --- End DRIM AI: VMind Initialization ---

  if (taskType === "visualization") {
    if (!dataset_json_str || !userPrompt || !fileName) {
      result = { error: "Missing dataset_json_str, userPrompt, or fileName for visualization task." };
    } else {
      result = await generateChart(vmindInstance, { dataset_json_str, userPrompt, directory, outputType, fileName, width, height, language });
    }
  } else if (taskType === "insight" && insightsId && insightsId.length > 0) {
    if (!fileName) {
      result = { error: "Missing fileName for insight task." };
    } else {
      result = await updateChartWithInsight(vmindInstance, { directory, fileName, outputType, insightsId });
    }
  } else {
    result = { error: `Unknown task_type '${taskType}' or missing parameters for insight task.` };
  }
  process.stdout.write(JSON.stringify(result));
}

main().catch(err => {
  console.error("DRIM AI (chartVisualize.ts): Unhandled error in main:", err);
  try {
    process.stdout.write(JSON.stringify({ error: `Unhandled script error in chartVisualize.ts: ${err.toString()}` }));
  } catch (e) {
    // If stdout itself fails
    console.error("DRIM AI (chartVisualize.ts): Failed to write error to stdout.");
  }
  process.exit(1);
});