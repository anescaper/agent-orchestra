use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use anyhow::Result;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub orchestra: OrchestraConfig,
    pub agents: AgentsConfig,
    pub outputs: OutputsConfig,
    pub digitalocean: DigitalOceanConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestraConfig {
    pub name: String,
    pub version: String,
    pub default_mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentsConfig {
    pub monitor: AgentConfig,
    pub analyzer: AgentConfig,
    pub researcher: AgentConfig,
    pub reporter: AgentConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentConfig {
    pub enabled: bool,
    pub timeout_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputsConfig {
    pub directory: String,
    pub retention_days: u32,
    pub formats: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DigitalOceanConfig {
    pub region: String,
    pub registry: String,
}

impl Config {
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = fs::read_to_string(path)?;
        let config: Config = serde_yaml::from_str(&content)?;
        Ok(config)
    }

    pub fn default() -> Self {
        Self {
            orchestra: OrchestraConfig {
                name: "Agent Orchestra".to_string(),
                version: "1.0.0".to_string(),
                default_mode: "auto".to_string(),
            },
            agents: AgentsConfig {
                monitor: AgentConfig {
                    enabled: true,
                    timeout_seconds: 120,
                },
                analyzer: AgentConfig {
                    enabled: true,
                    timeout_seconds: 180,
                },
                researcher: AgentConfig {
                    enabled: true,
                    timeout_seconds: 300,
                },
                reporter: AgentConfig {
                    enabled: true,
                    timeout_seconds: 120,
                },
            },
            outputs: OutputsConfig {
                directory: "outputs".to_string(),
                retention_days: 30,
                formats: vec!["json".to_string(), "txt".to_string()],
            },
            digitalocean: DigitalOceanConfig {
                region: "nyc3".to_string(),
                registry: "agent-orchestra".to_string(),
            },
        }
    }
}
