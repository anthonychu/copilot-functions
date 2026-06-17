# Azure Functions Agents - Front Matter Specification

## Overview

Each agent is defined in a `.agent.md` file with YAML front matter followed by markdown instructions. The front matter configures the agent's runtime behavior, while the markdown body contains the agent's system prompt.

### JSON Schema

A formal JSON Schema for the front matter format is available at [`front-matter-schema.json`](./front-matter-schema.json). This schema can be used for:

- **Editor support:** Enable autocomplete and IntelliSense in VS Code and other editors
- **Validation:** Validate `.agent.md` files in CI/CD pipelines
- **Documentation:** Auto-generate API documentation from the schema
- **Type safety:** Generate TypeScript types for programmatic agent configuration

**Using the schema in VS Code:**

Add to your workspace `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "docs/front-matter-schema.json": "**/*.agent.md"
  }
}
```

This enables:
- ✅ Autocomplete for field names
- ✅ IntelliSense with descriptions and examples
- ✅ Real-time validation errors
- ✅ Enum value suggestions

**Command-line validation:**

```bash
# Install dependencies
npm install -g yaml ajv-cli

# Extract and validate front matter
yq eval --front-matter=extract '.' my-agent.agent.md | \
  ajv validate -s docs/front-matter-schema.json -d /dev/stdin
```

**Programmatic usage (Node.js/TypeScript):**

```typescript
import Ajv from 'ajv';
import fs from 'fs';
import yaml from 'js-yaml';

const schema = JSON.parse(fs.readFileSync('docs/front-matter-schema.json', 'utf8'));
const ajv = new Ajv();
const validate = ajv.compile(schema);

// Extract front matter from .agent.md file
const agentFile = fs.readFileSync('my-agent.agent.md', 'utf8');
const frontMatterMatch = agentFile.match(/^---\n([\s\S]*?)\n---/);
const frontMatter = yaml.load(frontMatterMatch[1]);

if (validate(frontMatter)) {
  console.log('✅ Valid agent configuration');
} else {
  console.error('❌ Validation errors:', validate.errors);
}
```

## Field Summary

### Required
- `name` — Display name for the agent
- `description` — Brief description of the agent's purpose

### Core Configuration
- `trigger` — How the agent is invoked (HTTP, timer, queue, blob, etc.)
- `model` — LLM to use for this agent
- `timeout` — Maximum execution time in seconds

### Capabilities
- `execution_sandbox` — Python code execution environment
- `tools` — Control which tools are available
- `tools_from_connections` — Load connector-based tools (O365, Teams, SQL, etc.)
- `mcp_servers` — MCP servers to load for this agent
- `skills` — Domain knowledge to load from `skills/` directory

### Input/Output
- `input_schema` — Validate incoming HTTP requests
- `response_example` — Example output structure
- `response_schema` — JSON Schema for output validation

### Reliability & Governance
- `retry` — Automatic retry behavior for failures
- `metadata` — Version, owner, tags, and other organizational data

---

## Required Fields

### `name`
- **Type:** `string`
- **Description:** Display name for the agent
- **Example:** `"Daily Azure Report"`

### `description`
- **Type:** `string`  
- **Description:** Brief description of the agent's purpose (used for agent selection, logging, and documentation)
- **Example:** `"Lists resources created or changed in the last 24 hours and emails a report"`

---

## Optional Fields

### `trigger`
- **Type:** `object`
- **Description:** Defines how the agent is invoked. If omitted, defaults to HTTP trigger with default settings.
- **Structure:** Single key-value pair where the key is the trigger type and the value is the type-specific configuration

#### **HTTP Trigger** (default)
```yaml
trigger:
  http:
    route: string          # Optional. Custom route path. Defaults to function name
    methods: string[]      # Optional. Array of HTTP methods. Defaults to ["GET", "POST"]
    auth_level: string     # Optional. One of: anonymous, function, admin. Defaults to function
```

**Example:**
```yaml
trigger:
  http:
    route: "resource-summary"
    methods: ["POST"]
    auth_level: function
```

#### **Timer Trigger**
```yaml
trigger:
  timer:
    schedule: string       # Required. CRON expression (6-field format: second minute hour day month day-of-week)
```

**Example:**
```yaml
trigger:
  timer:
    schedule: "0 0 7 * * *"  # Daily at 7:00 AM UTC
```

#### **Queue Trigger**
```yaml
trigger:
  queue:
    name: string           # Required. Queue name
    connection: string     # Optional. App setting name for connection string. Defaults to AzureWebJobsStorage
```

#### **Blob Trigger**
```yaml
trigger:
  blob:
    path: string           # Required. Blob path pattern (e.g., "uploads/{name}.txt")
    connection: string     # Optional. App setting name for connection string. Defaults to AzureWebJobsStorage
```

#### **Event Grid Trigger**
```yaml
trigger:
  event_grid: {}           # No additional config required
```

#### **Service Bus Trigger**
```yaml
trigger:
  service_bus:
    queue_name: string           # Required if using queue. Queue name
    topic_name: string           # Required if using topic. Topic name
    subscription_name: string    # Required if using topic. Subscription name
    connection: string           # Optional. App setting name for connection string
```

---

### `execution_sandbox`
- **Type:** `object`
- **Description:** Configures Python code execution environment using Azure Container Apps dynamic sessions
- **Structure:**
```yaml
execution_sandbox:
  session_pool_management_endpoint: string  # Required. ACA session pool endpoint (typically env var)
```

**Example:**
```yaml
execution_sandbox:
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT
```

---

### `tools_from_connections`
- **Type:** `array`
- **Description:** Loads connector-based tools (e.g., Office 365, Outlook, SharePoint) from Azure Logic App connectors
- **Structure:**
```yaml
tools_from_connections:
  - connection_id: string  # Required. Connection resource ID (typically env var)
```

**Example:**
```yaml
tools_from_connections:
  - connection_id: $O365_CONNECTION_ID
  - connection_id: $OUTLOOK_CONNECTION_ID
```

---

### `response_example`
- **Type:** `string` (multiline)
- **Description:** Example response structure. Used for documentation and to guide the agent's output format
- **Best Practice:** Use for structured outputs (JSON, XML) from HTTP-triggered agents

**Example:**
```yaml
response_example: |
  {
    "total_resources": 42,
    "by_type": {
      "Microsoft.Web/sites": 5,
      "Microsoft.Storage/storageAccounts": 3
    },
    "by_location": {
      "eastus2": 20,
      "westus": 10
    }
  }
```

---

### `response_schema`
- **Type:** `object`
- **Description:** JSON Schema for validating and structuring agent outputs. More formal than `response_example`
- **Best Practice:** Use for HTTP-triggered agents that require strict output validation

**Example:**
```yaml
response_schema:
  type: object
  required: ["total_resources", "by_type"]
  properties:
    total_resources:
      type: integer
      minimum: 0
    by_type:
      type: object
      additionalProperties:
        type: integer
    by_location:
      type: object
      additionalProperties:
        type: integer
```

---

### `input_schema`
- **Type:** `object`
- **Description:** JSON Schema for validating incoming HTTP requests before invoking the agent
- **Best Practice:** Use to validate request bodies early and provide better error messages
- **Only applicable to:** HTTP-triggered agents

**Example:**
```yaml
input_schema:
  type: object
  required: ["subscription_id"]
  properties:
    subscription_id:
      type: string
      pattern: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
      description: "Azure subscription ID in UUID format"
    resource_group:
      type: string
      minLength: 1
      maxLength: 90
```

---

### `model`
- **Type:** `string` or `object`
- **Description:** Specifies which LLM to use for this agent. Overrides the global `COPILOT_MODEL` environment variable
- **Default:** Value of `COPILOT_MODEL` env var, or `"claude-sonnet-4"`

**Simple syntax:**
```yaml
model: gpt-4o
```

**Advanced syntax with parameters:**
```yaml
model:
  name: claude-sonnet-4
  temperature: 0.7
  max_tokens: 4000
```

**Use cases:**
- Use faster/cheaper models for simple tasks
- Use advanced models for complex reasoning
- Tune temperature for creative vs deterministic outputs

---

### `timeout`
- **Type:** `number`
- **Description:** Maximum execution time in seconds for the agent. Overrides the global `COPILOT_AGENT_TIMEOUT` environment variable
- **Default:** Value of `COPILOT_AGENT_TIMEOUT` env var, or `900` (15 minutes)

**Example:**
```yaml
timeout: 300  # 5 minutes
```

**Use case:** Prevent long-running agents from consuming excessive resources

---

### `tools`
- **Type:** `object`
- **Description:** Controls which tools are available to the agent. By default, all tools from `tools/` directory and built-in tools are loaded
- **Structure:**

```yaml
tools:
  include: string[]      # Optional. Only load these specific tools
  exclude: string[]      # Optional. Block these tools from being loaded
  only_custom: boolean   # Optional. If true, only load custom tools from tools/, no built-ins
```

**Examples:**

Include only specific tools:
```yaml
tools:
  include: ["azure_rest", "send_email"]
```

Exclude specific tools:
```yaml
tools:
  exclude: ["web_fetch", "bash", "execute_shell"]
```

Only custom tools:
```yaml
tools:
  only_custom: true
```

**Use cases:**
- Security: Restrict tool access for sensitive agents
- Performance: Reduce function schema size
- Clarity: Make agent capabilities explicit

---

### `mcp_servers`
- **Type:** `array` or `object`
- **Description:** MCP servers to load for this agent. Overrides or extends the global `mcp.json` configuration
- **Default:** Servers defined in `mcp.json` or `.vscode/mcp.json`

**Array syntax (reference by name):**
```yaml
mcp_servers:
  - microsoft-learn
  - azure-devops
```

**Object syntax (inline definition):**
```yaml
mcp_servers:
  custom-api:
    type: http
    url: https://api.example.com/mcp
    tools: ["search", "fetch"]
  local-tool:
    type: local
    command: python
    args: ["-m", "my_mcp_server"]
    tools: ["*"]
```

**Use case:** Different agents need different external capabilities; avoid loading all MCP tools globally

---

### `skills`
- **Type:** `array` or `boolean`
- **Description:** Controls which skills from the `skills/` directory are loaded for this agent
- **Default:** All skills in `skills/` directory are auto-discovered

**Load specific skills:**
```yaml
skills:
  - azure-resources
  - cost-optimization
```

**Disable all skills:**
```yaml
skills: false
```

**Use case:** Focus agent context on relevant domain knowledge only

---

### `retry`
- **Type:** `object`
- **Description:** Configures automatic retry behavior for failed agent executions
- **Default:** No automatic retries

**Structure:**
```yaml
retry:
  max_attempts: number     # Required. Maximum number of retry attempts
  backoff: string          # Optional. "linear" or "exponential". Default: "exponential"
  retry_on: string[]       # Optional. Conditions to retry on. Default: ["timeout", "error"]
  initial_delay: number    # Optional. Initial delay in seconds. Default: 1
  max_delay: number        # Optional. Maximum delay in seconds. Default: 60
```

**Example:**
```yaml
retry:
  max_attempts: 3
  backoff: exponential
  retry_on: ["timeout", "rate_limit", "service_unavailable"]
  initial_delay: 2
  max_delay: 30
```

**Use cases:**
- Resilience against transient failures
- Handling rate limits
- Dealing with unreliable external services

---

### `metadata`
- **Type:** `object`
- **Description:** Additional metadata for organization, discoverability, and governance
- **Fields are free-form** but common patterns include:

```yaml
metadata:
  version: string          # Semantic version of the agent
  owner: string           # Team or individual responsible
  tags: string[]          # Categorization tags
  documentation_url: string
  support_contact: string
```

**Example:**
```yaml
metadata:
  version: "1.2.0"
  owner: "platform-team@company.com"
  tags: ["production", "cost-optimization", "azure"]
  documentation_url: "https://wiki.company.com/agents/cost-optimizer"
  support_contact: "platform-team-slack"
```

**Use cases:**
- Agent lifecycle management
- Searchability and categorization
- Compliance and governance
- Support and ownership tracking

---

## Environment Variable Substitution

Use `$VARIABLE_NAME` syntax in any field value for runtime substitution from app settings or environment variables.

**Common patterns:**
- `$ACA_SESSION_POOL_ENDPOINT` — Session pool endpoint
- `$SUBSCRIPTION_ID` — Azure subscription ID
- `$O365_CONNECTION_ID` — Office 365 connection resource ID
- `$TO_EMAIL` — Recipient email address
- `$STORAGE_CONNECTION` — Storage account connection string

### Configuration Precedence

Some fields support both environment variables and front matter configuration. The order of precedence (highest to lowest):

1. **Front matter value** — Explicit value in the `.agent.md` file
2. **Environment variable** — Global configuration via app settings
3. **Default value** — Built-in framework default

**Examples:**

**Model selection:**
1. `model: gpt-4o` in front matter (highest priority)
2. `COPILOT_MODEL` environment variable
3. `claude-sonnet-4` (default)

**Timeout:**
1. `timeout: 300` in front matter (highest priority)
2. `COPILOT_AGENT_TIMEOUT` environment variable
3. `900` seconds / 15 minutes (default)

---

## Complete Examples

### HTTP-Triggered Agent with Schema Validation
```yaml
---
name: Resource Summary
description: Returns a structured summary of Azure resources

trigger:
  http:
    route: "resource-summary"
    methods: ["POST"]
    auth_level: function

input_schema:
  type: object
  required: ["subscription_id"]
  properties:
    subscription_id:
      type: string
      pattern: "^[0-9a-f-]+$"

response_schema:
  type: object
  required: ["total_resources", "by_type"]
  properties:
    total_resources:
      type: integer
    by_type:
      type: object
    by_location:
      type: object

model: gpt-4o
timeout: 120

tools:
  include: ["azure_rest"]

skills:
  - azure-resources

metadata:
  version: "1.0.0"
  owner: "platform-team@company.com"
  tags: ["production", "azure", "reporting"]
---

Given the subscription ID in the request body, list all resources and return a structured summary.
```

### Timer-Triggered Agent with Email Integration
```yaml
---
name: Daily Azure Report
description: Lists resources created or changed in the last 24 hours and emails a report

trigger:
  timer:
    schedule: "0 0 7 * * *"

tools_from_connections:
  - connection_id: $O365_CONNECTION_ID

mcp_servers:
  - microsoft-learn

retry:
  max_attempts: 3
  backoff: exponential
  retry_on: ["timeout", "error"]

metadata:
  version: "2.1.0"
  owner: "infrastructure-team@company.com"
  tags: ["scheduled", "reporting", "email"]
---

When triggered, list all resources in subscription $SUBSCRIPTION_ID, filter for changes in the last 24 hours, and email a report to $TO_EMAIL.
```

### Interactive Chat Agent with Code Execution
```yaml
---
name: Chat Assistant
description: A helpful assistant with Python code execution capabilities

execution_sandbox:
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT

model:
  name: claude-sonnet-4
  temperature: 0.7

timeout: 600

tools:
  exclude: ["bash", "execute_shell"]
---

You are a helpful assistant. If you need to run Python code or perform calculations, use the code execution sandbox.
```

### Minimal Agent (Defaults)
```yaml
---
name: Azure Assistant
description: An interactive assistant for exploring Azure resources
---

Help the user explore resources in subscription $SUBSCRIPTION_ID.
```

---

## Validation Rules

1. **Required fields:** `name` and `description` must always be present
2. **Trigger mutual exclusivity:** Only one trigger type can be specified per agent
3. **Trigger type-specific validation:** Each trigger type validates its own required fields
4. **Environment variables:** `$VARIABLE_NAME` references must be defined in app settings at runtime
5. **CRON expressions:** Timer trigger schedules must be valid 6-field CRON expressions
6. **HTTP methods:** Must be valid HTTP verbs (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)
7. **Auth levels:** Must be one of: `anonymous`, `function`, `admin`
8. **Schema validation:** `input_schema` and `response_schema` must be valid JSON Schema (draft-07 or later)
9. **Model names:** Must be valid Copilot SDK model identifiers (e.g., `claude-sonnet-4`, `gpt-4o`, `o1`, `o1-mini`)
10. **Timeout limits:** Must be positive numbers; consider Azure Functions timeout limits (5 min for Consumption, 30 min for Premium)
11. **Tool references:** Tools in `tools.include` must exist in `tools/` directory or be built-in tools
12. **MCP server references:** Servers in `mcp_servers` array must be defined in `mcp.json` or inline
13. **Skill references:** Skills in `skills` array must exist as directories under `skills/`
14. **Retry attempts:** `retry.max_attempts` must be >= 1 and <= 10 (recommended)
15. **Retry backoff:** `retry.backoff` must be either `"linear"` or `"exponential"`

---

## File Naming Conventions

- **Primary agent:** `main.agent.md` or `function_app.agent.md`
- **Named agents:** `{agent-name}.agent.md` (e.g., `daily_azure_report.agent.md`)
- **Skills:** `skills/{skill-name}/SKILL.md`

---

## Skills Front Matter

Skills use a simplified front matter structure:

```yaml
---
name: string        # Required. Skill name
description: string # Required. When this skill should be used
---
```

Skills contain domain-specific knowledge and are referenced by agents but don't have triggers or tool configurations.

---

## Implementation Status

This specification includes both currently implemented features and proposed enhancements. Implementation status by field:

### ✅ Fully Implemented
- `name`, `description` — Core metadata
- `trigger` (all types) — Trigger configuration
- `execution_sandbox` — Code execution
- `tools_from_connections` — Connector tools
- `response_example` — Output examples
- `response_schema` — Output validation (implemented but undocumented)

### 🚧 Partially Implemented / Requires Framework Changes
- `model` — Currently only configurable globally via `COPILOT_MODEL` env var
- `timeout` — Currently only configurable globally via `COPILOT_AGENT_TIMEOUT` env var
- `mcp_servers` — Currently only configurable globally via `mcp.json`
- `skills` — Currently all skills are auto-discovered
- `tools` — Currently all tools are loaded globally

### 📋 Proposed / Not Yet Implemented
- `input_schema` — HTTP request validation
- `retry` — Automatic retry behavior
- `metadata` — Organizational metadata

**Note:** Proposed fields represent the intended direction of the programming model. Implementation requires updates to the `azure-functions-agents` framework.

---

## Resources

- **JSON Schema:** [`front-matter-schema.json`](./front-matter-schema.json) — Formal schema for validation and editor support
- **Trigger Reference:** [`triggers.md`](./triggers.md) — Detailed documentation for all trigger types
- **Sample Projects:** [`../samples/`](../samples/) — Working examples demonstrating various agent patterns
