export interface Env {
  BACKEND_URL: string;
  WORKER_KEY_ID: string;
  WORKER_SECRET: string;
  INBOUND_AUTH_TOKEN?: string;
  ALLOW_WRITES?: string;
}

type McpCallBody = {
  id?: string | number | null;
  method?: string;
  params?: {
    name?: string;
    arguments?: Record<string, unknown>;
    [key: string]: unknown;
  };
};

type OperationalContext = {
  tenant_id?: string | null;
  active_property_id?: string | null;
  resolved_from_query?: string | null;
  resolved_from_property_id?: string | null;
};

const encoder = new TextEncoder();
const ADMIN_HIDDEN_TOOLS = new Set(["list_my_properties", "select_my_property"]);
const ADMIN_WRITE_TOOLS = new Set<string>();
const ADMIN_READ_ONLY_TOOLS = new Set([
  "search_properties",
  "list_tenant_contexts",
  "get_active_context",
  "get_property_details",
  "get_reporting_metadata",
  "run_report",
  "run_realtime_report",
  "get_traffic_overview",
  "get_page_performance",
  "compare_date_ranges"
]);
const ADMIN_IDEMPOTENT_TOOLS = new Set([
  ...ADMIN_READ_ONLY_TOOLS,
  "clear_active_context",
  "select_client_context",
  "select_property_context",
  "sync_account_properties"
]);

type JsonRpcLike = {
  jsonrpc?: string;
  id?: string | number | null;
  result?: {
    tools?: Array<{
      name?: string;
      annotations?: Record<string, unknown>;
      [key: string]: unknown;
    }>;
    content?: Array<{
      type?: string;
      text?: string;
    }>;
  };
};

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = stableValue((value as Record<string, unknown>)[key]);
        return acc;
      }, {});
  }
  return value;
}

async function hmacHex(secret: string, value: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(value));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function parseMcpCallBody(body: string): McpCallBody {
  try {
    return JSON.parse(body) as McpCallBody;
  } catch {
    return {};
  }
}

function buildSseMessage(payload: unknown): string {
  return `event: message\ndata: ${JSON.stringify(payload)}\n\n`;
}

function buildToolErrorResponse(id: string | number | null | undefined, toolName: string, message: string): string {
  return buildSseMessage({
    jsonrpc: "2.0",
    id: id ?? null,
    result: {
      content: [{ type: "text", text: `Error executing tool ${toolName}: ${message}` }],
      isError: true
    }
  });
}

function canonicalMessage(
  requestName: string,
  payload: Record<string, unknown>,
  tenantId: string | null,
  timestamp: string,
  operationalContext: OperationalContext | null
): string {
  return JSON.stringify(
    stableValue({
      request_name: requestName,
      payload,
      tenant_id: tenantId,
      timestamp,
      operational_context: operationalContext
    })
  );
}

function getSessionId(request: Request): string {
  return (
    request.headers.get("x-openai-session") ??
    request.headers.get("x-openai-subject") ??
    request.headers.get("mcp-session-id") ??
    request.headers.get("x-admin-session") ??
    "default"
  );
}

function getConfiguredInboundToken(env: Env): string | null {
  const token = env.INBOUND_AUTH_TOKEN?.trim();
  return token ? token : null;
}

function getInboundRequestToken(request: Request): string | null {
  const bearer = request.headers.get("authorization");
  if (bearer?.toLowerCase().startsWith("bearer ")) return bearer.slice(7).trim();
  const explicitToken = request.headers.get("x-mcp-auth")?.trim();
  return explicitToken || null;
}

function parseMcpSsePayload(responseText: string): JsonRpcLike | null {
  const line = responseText.split(/\r?\n/).find((entry) => entry.startsWith("data: "));
  if (!line) return null;
  try {
    return JSON.parse(line.slice(6)) as JsonRpcLike;
  } catch {
    return null;
  }
}

function isWritesAllowed(env: Env): boolean {
  const value = env.ALLOW_WRITES?.trim().toLowerCase();
  return value !== "false";
}

function filterAdminToolsList(responseText: string, env: Env): string {
  const payload = parseMcpSsePayload(responseText);
  const tools = payload?.result?.tools;
  if (!payload || !Array.isArray(tools)) return responseText;

  const allowWrites = isWritesAllowed(env);
  return buildSseMessage({
    ...payload,
    result: {
      ...payload.result,
      tools: tools
        .filter((tool) => {
          const toolName = String(tool?.name ?? "");
          if (ADMIN_HIDDEN_TOOLS.has(toolName)) return false;
          if (!allowWrites && ADMIN_WRITE_TOOLS.has(toolName)) return false;
          return true;
        })
        .map((tool) => ({
          ...tool,
          annotations: {
            ...tool.annotations,
            ...buildToolAnnotations(String(tool?.name ?? ""))
          }
        }))
    }
  });
}

function buildToolAnnotations(toolName: string): Record<string, boolean> {
  return {
    readOnlyHint: ADMIN_READ_ONLY_TOOLS.has(toolName),
    destructiveHint: false,
    idempotentHint: ADMIN_IDEMPOTENT_TOOLS.has(toolName),
    openWorldHint: false
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });

    const configuredInboundToken = getConfiguredInboundToken(env);
    if (configuredInboundToken !== null) {
      const providedInboundToken = getInboundRequestToken(request);
      if (providedInboundToken !== configuredInboundToken) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), {
          status: 401,
          headers: { "content-type": "application/json" }
        });
      }
    }

    const sessionId = getSessionId(request);
    const bodyText = await request.text();
    const body = parseMcpCallBody(bodyText);
    const requestName = body.method;
    const toolName = body.method === "tools/call" ? body.params?.name : undefined;
    const args =
      body.method === "tools/call"
        ? body.params?.arguments ?? {}
        : ((body.params ?? {}) as Record<string, unknown>);

    if (!requestName) {
      return new Response(JSON.stringify({ error: "Expected MCP payload with method" }), {
        status: 400,
        headers: { "content-type": "application/json" }
      });
    }

    if (body.method === "tools/call" && toolName && ADMIN_HIDDEN_TOOLS.has(toolName)) {
      return new Response(buildToolErrorResponse(body.id, toolName, `${toolName} is available only to client workers`), {
        status: 200,
        headers: { "content-type": "text/event-stream" }
      });
    }
    if (body.method === "tools/call" && toolName && !isWritesAllowed(env) && ADMIN_WRITE_TOOLS.has(toolName)) {
      return new Response(buildToolErrorResponse(body.id, toolName, `${toolName} is disabled for this admin worker`), {
        status: 200,
        headers: { "content-type": "text/event-stream" }
      });
    }

    const operationName = body.method === "tools/call" ? toolName ?? requestName : requestName;
    const operationalContext: OperationalContext | null = null;
    const timestamp = new Date().toISOString();
    const signature = await hmacHex(env.WORKER_SECRET, canonicalMessage(operationName, args, null, timestamp, operationalContext));

    const headers: HeadersInit = {
      "content-type": "application/json",
      accept: request.headers.get("accept") ?? "application/json, text/event-stream",
      authorization: `Bearer ${env.WORKER_SECRET}`,
      "x-worker-type": "admin",
      "x-worker-key-id": env.WORKER_KEY_ID,
      "x-worker-session-id": sessionId,
      "x-request-timestamp": timestamp,
      "x-context-signature": signature
    };

    if (operationalContext) headers["x-resolved-context"] = JSON.stringify(operationalContext);
    const mcpSessionId = request.headers.get("mcp-session-id");
    if (mcpSessionId) headers["mcp-session-id"] = mcpSessionId;

    const backendResponse = await fetch(`${env.BACKEND_URL}/mcp/mcp`, {
      method: "POST",
      headers,
      body: bodyText
    });

    const rawResponseText = await backendResponse.text();
    const responseText = backendResponse.ok && body.method === "tools/list" ? filterAdminToolsList(rawResponseText, env) : rawResponseText;
    return new Response(responseText, {
      status: backendResponse.status,
      headers: backendResponse.headers
    });
  }
};
