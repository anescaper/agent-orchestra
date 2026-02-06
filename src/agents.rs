use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Clone)]
pub struct AgentTask {
    pub name: String,
    pub prompt: String,
}

impl AgentTask {
    pub fn new(name: impl Into<String>, prompt: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            prompt: prompt.into(),
        }
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
    pub timestamp: DateTime<Utc>,
}

impl AgentResult {
    pub fn success(agent: String, output: String) -> Self {
        Self {
            agent,
            status: "success".to_string(),
            output: Some(output),
            error: None,
            timestamp: Utc::now(),
        }
    }

    pub fn failed(agent: String, error: String) -> Self {
        Self {
            agent,
            status: "failed".to_string(),
            output: None,
            error: Some(error),
            timestamp: Utc::now(),
        }
    }
}

// Future: Add specific agent implementations here
// For example:
// pub mod monitor;
// pub mod analyzer;
// pub mod researcher;
