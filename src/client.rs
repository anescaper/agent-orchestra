use anyhow::{Context, Result};
use async_trait::async_trait;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::fmt;
use tracing::{error, info, warn};

const ANTHROPIC_API_URL: &str = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION: &str = "2023-06-01";
const DEFAULT_MODEL: &str = "claude-sonnet-4-20250514";

/// The supported client modes.
#[derive(Debug, Clone, PartialEq)]
pub enum ClientMode {
    Api,
    ClaudeCode,
    Hybrid,
    AgentTeams,
}

impl fmt::Display for ClientMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ClientMode::Api => write!(f, "api"),
            ClientMode::ClaudeCode => write!(f, "claude-code"),
            ClientMode::Hybrid => write!(f, "hybrid"),
            ClientMode::AgentTeams => write!(f, "agent-teams"),
        }
    }
}

impl ClientMode {
    pub fn from_str(s: &str) -> Result<Self> {
        match s {
            "api" => Ok(ClientMode::Api),
            "claude-code" => Ok(ClientMode::ClaudeCode),
            "hybrid" => Ok(ClientMode::Hybrid),
            "agent-teams" => Ok(ClientMode::AgentTeams),
            other => anyhow::bail!(
                "Invalid CLIENT_MODE '{}'. Must be 'api', 'claude-code', 'hybrid', or 'agent-teams'.",
                other
            ),
        }
    }
}

/// Trait for sending prompts to a Claude backend.
#[async_trait]
pub trait AgentClient: Send + Sync {
    /// Send a prompt with an optional system prompt.
    async fn send_message(&self, prompt: &str, system_prompt: Option<&str>) -> Result<String>;
}

// ---------------------------------------------------------------------------
// API client (paid) — uses the Anthropic HTTP API
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
struct MessageRequest {
    model: String,
    max_tokens: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    system: Option<String>,
    messages: Vec<Message>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct Message {
    role: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct MessageResponse {
    content: Vec<ContentBlock>,
    #[allow(dead_code)]
    id: String,
    #[allow(dead_code)]
    model: String,
    #[allow(dead_code)]
    role: String,
}

#[derive(Debug, Deserialize)]
struct ContentBlock {
    #[serde(rename = "type")]
    #[allow(dead_code)]
    content_type: String,
    text: String,
}

pub struct ApiClient {
    client: Client,
    api_key: String,
    model: String,
}

impl ApiClient {
    pub fn new(api_key: String) -> Self {
        Self {
            client: Client::new(),
            api_key,
            model: DEFAULT_MODEL.to_string(),
        }
    }

    pub fn with_model(mut self, model: &str) -> Self {
        self.model = model.to_string();
        self
    }
}

#[async_trait]
impl AgentClient for ApiClient {
    async fn send_message(&self, prompt: &str, system_prompt: Option<&str>) -> Result<String> {
        let request = MessageRequest {
            model: self.model.clone(),
            max_tokens: 4096,
            system: system_prompt.map(|s| s.to_string()),
            messages: vec![Message {
                role: "user".to_string(),
                content: prompt.to_string(),
            }],
        };

        let response = self
            .client
            .post(ANTHROPIC_API_URL)
            .header("x-api-key", &self.api_key)
            .header("anthropic-version", ANTHROPIC_VERSION)
            .header("content-type", "application/json")
            .json(&request)
            .send()
            .await
            .context("Failed to send request to Anthropic API")?;

        if !response.status().is_success() {
            let status = response.status();
            let error_text = response.text().await.unwrap_or_default();
            anyhow::bail!("API request failed with status {}: {}", status, error_text);
        }

        let message_response: MessageResponse = response
            .json()
            .await
            .context("Failed to parse API response")?;

        let text = message_response
            .content
            .first()
            .map(|block| block.text.clone())
            .unwrap_or_default();

        Ok(text)
    }
}

// ---------------------------------------------------------------------------
// CLI client (free) — shells out to `claude -p "prompt"`
// ---------------------------------------------------------------------------

pub struct CliClient {
    cli_path: String,
}

impl CliClient {
    pub fn new() -> Self {
        Self {
            cli_path: "/home/claude/.local/bin/claude".to_string(),
        }
    }
}

#[async_trait]
impl AgentClient for CliClient {
    async fn send_message(&self, prompt: &str, system_prompt: Option<&str>) -> Result<String> {
        // If a system prompt is provided, prepend it as context
        let full_prompt = match system_prompt {
            Some(sys) => format!("[CONTEXT: {}]\n\n{}", sys, prompt),
            None => prompt.to_string(),
        };

        let output = tokio::process::Command::new(&self.cli_path)
            .arg("-p")
            .arg(&full_prompt)
            .env_remove("ANTHROPIC_API_KEY")
            .output()
            .await
            .context("Failed to execute claude CLI")?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stdout = String::from_utf8_lossy(&output.stdout);
            let detail = if !stderr.is_empty() {
                &stderr
            } else {
                &stdout
            };
            anyhow::bail!(
                "claude CLI exited with {}: {}",
                output.status,
                detail.trim()
            );
        }

        let text = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(text)
    }
}

// ---------------------------------------------------------------------------
// Hybrid client — tries API first, falls back to CLI
// ---------------------------------------------------------------------------

pub struct HybridClient {
    api: ApiClient,
    cli: CliClient,
}

impl HybridClient {
    pub fn new(api_key: String) -> Self {
        Self {
            api: ApiClient::new(api_key),
            cli: CliClient::new(),
        }
    }

    pub fn with_model(mut self, model: &str) -> Self {
        self.api = self.api.with_model(model);
        self
    }
}

#[async_trait]
impl AgentClient for HybridClient {
    async fn send_message(&self, prompt: &str, system_prompt: Option<&str>) -> Result<String> {
        // Try API first
        match self.api.send_message(prompt, system_prompt).await {
            Ok(response) => {
                info!("Hybrid: API succeeded");
                Ok(response)
            }
            Err(api_err) => {
                warn!("Hybrid: API failed ({:#}), falling back to CLI", api_err);
                self.cli
                    .send_message(prompt, system_prompt)
                    .await
                    .context("Hybrid: both API and CLI failed")
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Agent Teams client — spawns `claude` with Agent Teams env
// ---------------------------------------------------------------------------

pub struct TeamsClient {
    cli_path: String,
}

impl TeamsClient {
    pub fn new() -> Self {
        // Prefer the local `claude` on PATH, fall back to known paths
        let cli_path = std::env::var("CLAUDE_CLI_PATH").unwrap_or_else(|_| {
            if std::path::Path::new("/usr/local/bin/claude").exists() {
                "/usr/local/bin/claude".to_string()
            } else {
                "claude".to_string()
            }
        });
        Self { cli_path }
    }
}

#[async_trait]
impl AgentClient for TeamsClient {
    async fn send_message(&self, prompt: &str, system_prompt: Option<&str>) -> Result<String> {
        let full_prompt = match system_prompt {
            Some(sys) => format!("[TEAM CONTEXT: {}]\n\n{}", sys, prompt),
            None => prompt.to_string(),
        };

        info!("TeamsClient: launching claude with Agent Teams enabled");

        let output = tokio::process::Command::new(&self.cli_path)
            .arg("-p")
            .arg(&full_prompt)
            .env("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
            .env_remove("ANTHROPIC_API_KEY")
            .output()
            .await
            .context("Failed to execute claude CLI with Agent Teams")?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stdout = String::from_utf8_lossy(&output.stdout);
            let detail = if !stderr.is_empty() {
                &stderr
            } else {
                &stdout
            };
            error!("TeamsClient: claude exited with {}", output.status);
            anyhow::bail!(
                "claude CLI (agent-teams) exited with {}: {}",
                output.status,
                detail.trim()
            );
        }

        let text = String::from_utf8_lossy(&output.stdout).to_string();
        info!("TeamsClient: session completed ({} bytes output)", text.len());
        Ok(text)
    }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

pub fn create_client(mode: &ClientMode, api_key: Option<String>) -> Result<Box<dyn AgentClient>> {
    match mode {
        ClientMode::Api => {
            let key =
                api_key.context("ANTHROPIC_API_KEY is required when CLIENT_MODE=api")?;
            Ok(Box::new(ApiClient::new(key)))
        }
        ClientMode::ClaudeCode => Ok(Box::new(CliClient::new())),
        ClientMode::Hybrid => {
            let key =
                api_key.context("ANTHROPIC_API_KEY is required when CLIENT_MODE=hybrid")?;
            Ok(Box::new(HybridClient::new(key)))
        }
        ClientMode::AgentTeams => Ok(Box::new(TeamsClient::new())),
    }
}

/// Create a client for a specific agent, respecting per-agent overrides.
/// Falls back to the global mode if the agent doesn't specify one.
pub fn create_agent_client(
    agent_mode: Option<&str>,
    global_mode: &ClientMode,
    api_key: Option<String>,
) -> Result<Box<dyn AgentClient>> {
    let mode = match agent_mode {
        Some(m) => ClientMode::from_str(m)?,
        None => global_mode.clone(),
    };
    create_client(&mode, api_key)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_api_client_creation() {
        let client = ApiClient::new("test-key".to_string());
        assert_eq!(client.api_key, "test-key");
        assert_eq!(client.model, DEFAULT_MODEL);
    }

    #[test]
    fn test_api_client_with_model() {
        let client = ApiClient::new("test-key".to_string()).with_model("claude-opus-4-6");
        assert_eq!(client.model, "claude-opus-4-6");
    }

    #[test]
    fn test_cli_client_creation() {
        let client = CliClient::new();
        assert_eq!(client.cli_path, "/home/claude/.local/bin/claude");
    }

    #[test]
    fn test_client_mode_from_str() {
        assert_eq!(ClientMode::from_str("api").unwrap(), ClientMode::Api);
        assert_eq!(
            ClientMode::from_str("claude-code").unwrap(),
            ClientMode::ClaudeCode
        );
        assert_eq!(
            ClientMode::from_str("hybrid").unwrap(),
            ClientMode::Hybrid
        );
        assert_eq!(
            ClientMode::from_str("agent-teams").unwrap(),
            ClientMode::AgentTeams
        );
        assert!(ClientMode::from_str("invalid").is_err());
    }

    #[test]
    fn test_client_mode_display() {
        assert_eq!(ClientMode::Api.to_string(), "api");
        assert_eq!(ClientMode::ClaudeCode.to_string(), "claude-code");
        assert_eq!(ClientMode::Hybrid.to_string(), "hybrid");
        assert_eq!(ClientMode::AgentTeams.to_string(), "agent-teams");
    }

    #[test]
    fn test_create_client_api_requires_key() {
        let result = create_client(&ClientMode::Api, None);
        assert!(result.is_err());
    }

    #[test]
    fn test_create_client_api_with_key() {
        let result = create_client(&ClientMode::Api, Some("sk-test".to_string()));
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_client_claude_code() {
        let result = create_client(&ClientMode::ClaudeCode, None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_client_hybrid_requires_key() {
        let result = create_client(&ClientMode::Hybrid, None);
        assert!(result.is_err());
    }

    #[test]
    fn test_create_client_hybrid_with_key() {
        let result = create_client(&ClientMode::Hybrid, Some("sk-test".to_string()));
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_agent_client_override() {
        let result = create_agent_client(
            Some("claude-code"),
            &ClientMode::Api,
            Some("sk-test".to_string()),
        );
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_agent_client_fallback() {
        let result = create_agent_client(None, &ClientMode::ClaudeCode, None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_agent_client_invalid_override() {
        let result = create_agent_client(Some("bad"), &ClientMode::Api, Some("sk".to_string()));
        assert!(result.is_err());
    }

    #[test]
    fn test_create_client_agent_teams() {
        let result = create_client(&ClientMode::AgentTeams, None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_teams_client_creation() {
        let _client = TeamsClient::new();
        // TeamsClient doesn't require an API key
    }
}
