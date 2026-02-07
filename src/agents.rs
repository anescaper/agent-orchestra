use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone)]
pub struct AgentTask {
    pub name: String,
    pub prompt: String,
    pub timeout_seconds: u64,
    /// Per-agent client mode override (e.g. "api", "claude-code", "hybrid").
    pub client_mode: Option<String>,
    /// System prompt giving this agent its role/identity.
    pub system_prompt: Option<String>,
}

impl AgentTask {
    pub fn new(name: impl Into<String>, prompt: impl Into<String>, timeout_seconds: u64) -> Self {
        Self {
            name: name.into(),
            prompt: prompt.into(),
            timeout_seconds,
            client_mode: None,
            system_prompt: None,
        }
    }

    pub fn with_client_mode(mut self, mode: Option<String>) -> Self {
        self.client_mode = mode;
        self
    }

    pub fn with_system_prompt(mut self, prompt: Option<String>) -> Self {
        self.system_prompt = prompt;
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentResult {
    pub agent: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub client_mode: String,
    pub timestamp: DateTime<Utc>,
}

impl AgentResult {
    pub fn success(agent: String, output: String, client_mode: String) -> Self {
        Self {
            agent,
            status: "success".to_string(),
            output: Some(output),
            error: None,
            client_mode,
            timestamp: Utc::now(),
        }
    }

    pub fn failed(agent: String, error: String, client_mode: String) -> Self {
        Self {
            agent,
            status: "failed".to_string(),
            output: None,
            error: Some(error),
            client_mode,
            timestamp: Utc::now(),
        }
    }
}
