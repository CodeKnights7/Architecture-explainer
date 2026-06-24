#!/usr/bin/env node
/**
 * mcp/wiki-server.js
 * ==================
 * Lightweight MCP-compatible Wikipedia search server.
 *
 * Transport  : HTTP (not stdio) so any language can call it via a simple
 *              POST request.  The Python module (wiki_enrichment.py) hits
 *              http://localhost:3333/wiki.
 *
 * Wikipedia  : Public REST API — no API key required.
 *              https://en.wikipedia.org/api/rest_v1/page/summary/{title}
 *
 * Start      : node mcp/wiki-server.js
 *              (or via npm start / the MCP config below)
 *
 * MCP config (claude_desktop_config.json)
 * ----------------------------------------
 * "mcpServers": {
 *   "wikipedia": {
 *     "command": "node",
 *     "args": ["mcp/wiki-server.js"]
 *   }
 * }
 *
 * POST /wiki
 * ----------
 * Body (JSON):  { "query": "Apache Kafka" }
 * Response:     { "title": "...", "extract": "...", "url": "..." }
 *               { "error": "Not found" }  on 404
 *
 * GET /health
 * -----------
 * Response:     { "status": "ok", "service": "wiki-mcp-server" }
 */

"use strict";

const http  = require("http");
const https = require("https");

const PORT = process.env.WIKI_MCP_PORT || 3333;

// ---------------------------------------------------------------------------
// Wikipedia REST API helper
// ---------------------------------------------------------------------------

/**
 * Fetch a summary from the Wikipedia REST API.
 * @param {string} title  - Wikipedia article title (URL-encoded internally)
 * @returns {Promise<{title:string, extract:string, url:string}|null>}
 */
function fetchWikiSummary(title) {
  return new Promise((resolve) => {
    const encoded = encodeURIComponent(title.trim());
    const url     = `https://en.wikipedia.org/api/rest_v1/page/summary/${encoded}`;

    const options = {
      headers: {
        "User-Agent": "ArchitectureAI-MCP/4.0 (diagram analysis tool; Node.js)",
        "Accept":     "application/json",
      },
    };

    https.get(url, options, (res) => {
      let body = "";
      res.on("data",  (chunk) => { body += chunk; });
      res.on("end",   () => {
        try {
          if (res.statusCode !== 200) {
            resolve(null);
            return;
          }
          const data = JSON.parse(body);
          // Reject disambiguation pages.
          if (data.type === "disambiguation") {
            resolve(null);
            return;
          }
          resolve({
            title:   data.title   || title,
            extract: data.extract || "",
            url:     data.content_urls?.desktop?.page || "",
          });
        } catch (_) {
          resolve(null);
        }
      });
      res.on("error", () => resolve(null));
    }).on("error", () => resolve(null));
  });
}

// ---------------------------------------------------------------------------
// Title normalisation map (mirrors wiki_enrichment.py)
// ---------------------------------------------------------------------------

const TITLE_MAP = {
  "microservices":       "Microservices",
  "microservice":        "Microservices",
  "api gateway":         "API gateway",
  "event-driven":        "Event-driven architecture",
  "service mesh":        "Service mesh",
  "serverless":          "Serverless computing",
  "load balancer":       "Load balancing (computing)",
  "cdn":                 "Content delivery network",
  "postgresql":          "PostgreSQL",
  "postgres":            "PostgreSQL",
  "mysql":               "MySQL",
  "mongodb":             "MongoDB",
  "redis":               "Redis",
  "cassandra":           "Apache Cassandra",
  "elasticsearch":       "Elasticsearch",
  "dynamodb":            "Amazon DynamoDB",
  "kafka":               "Apache Kafka",
  "apache kafka":        "Apache Kafka",
  "rabbitmq":            "RabbitMQ",
  "sqs":                 "Amazon Simple Queue Service",
  "aws":                 "Amazon Web Services",
  "azure":               "Microsoft Azure",
  "gcp":                 "Google Cloud Platform",
  "google cloud":        "Google Cloud Platform",
  "kubernetes":          "Kubernetes",
  "k8s":                 "Kubernetes",
  "docker":              "Docker (software)",
  "prometheus":          "Prometheus (software)",
  "grafana":             "Grafana",
  "datadog":             "Datadog",
  "waf":                 "Web application firewall",
  "oauth":               "OAuth",
  "jwt":                 "JSON Web Token",
  "zero trust":          "Zero trust security model",
  "spark":               "Apache Spark",
  "airflow":             "Apache Airflow",
  "terraform":           "Terraform (software)",
};

function resolveTitle(query) {
  const lower = query.toLowerCase().trim();
  if (TITLE_MAP[lower]) return TITLE_MAP[lower];
  // Strip common suffixes.
  for (const suffix of [" service", " db", " database", " queue", " storage"]) {
    if (lower.endsWith(suffix)) {
      const stem = lower.slice(0, -suffix.length).trim();
      if (TITLE_MAP[stem]) return TITLE_MAP[stem];
    }
  }
  // Default: title-case.
  return query.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

const server = http.createServer(async (req, res) => {

  // CORS for local development / Claude Desktop.
  res.setHeader("Access-Control-Allow-Origin",  "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  // ---- Health check -------------------------------------------------------
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", service: "wiki-mcp-server", port: PORT }));
    return;
  }

  // ---- Wiki search --------------------------------------------------------
  if (req.method === "POST" && req.url === "/wiki") {
    let body = "";
    req.on("data",  (chunk) => { body += chunk; });
    req.on("end",   async () => {
      try {
        const payload = JSON.parse(body || "{}");
        const query   = (payload.query || "").trim();

        if (!query) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "Missing 'query' field" }));
          return;
        }

        const title  = resolveTitle(query);
        const result = await fetchWikiSummary(title);

        if (!result) {
          res.writeHead(404, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "Not found", query, title }));
          return;
        }

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(result));

      } catch (err) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Internal server error", detail: err.message }));
      }
    });
    return;
  }

  // ---- 404 ----------------------------------------------------------------
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not found" }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[wiki-mcp-server] Listening on http://127.0.0.1:${PORT}`);
  console.log(`[wiki-mcp-server] POST /wiki  { "query": "Apache Kafka" }`);
  console.log(`[wiki-mcp-server] GET  /health`);
});

server.on("error", (err) => {
  console.error(`[wiki-mcp-server] Error: ${err.message}`);
  process.exit(1);
});