import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import { Readable } from "node:stream";
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { AgnoAgent } from "@ag-ui/agno";

dotenv.config({ path: ".env.local" });
dotenv.config();

const port = Number(process.env.COPILOTKIT_PORT ?? 3000);
const aguiUrl = process.env.AGNO_AGENT_URL ?? "http://localhost:8000/agui";

const serviceAdapter = new ExperimentalEmptyAdapter();
const runtime = new CopilotRuntime({
  agents: {
    studybuddy_agent: new AgnoAgent({ url: aguiUrl }),
  },
});

const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
  runtime,
  serviceAdapter,
  endpoint: "/api/copilotkit",
});

const app = express();
app.use(cors({ origin: true }));
app.use(express.raw({ type: "*/*" }));

function toHeaders(entries: express.Request["headers"]): Headers {
  const headers = new Headers();
  Object.entries(entries).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined) {
          headers.append(key, item);
        }
      });
      return;
    }
    if (value !== undefined) {
      headers.append(key, value);
    }
  });
  return headers;
}

app.post("/api/copilotkit", async (req, res) => {
  const request = new Request(`http://localhost:${port}${req.originalUrl}`, {
    method: req.method,
    headers: toHeaders(req.headers),
    body: req.body && req.body.length ? req.body : undefined,
  });

  const response = await handleRequest(request);

  response.headers.forEach((value, key) => {
    res.setHeader(key, value);
  });
  res.status(response.status);

  if (!response.body) {
    res.end();
    return;
  }

  const nodeStream = Readable.fromWeb(response.body as unknown as ReadableStream);
  nodeStream.pipe(res);
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", aguiUrl });
});

app.listen(port, () => {
  console.log(`CopilotKit dev bridge listening on http://localhost:${port}`);
  console.log(`Proxying requests to ${aguiUrl}`);
});
