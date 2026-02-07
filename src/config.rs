use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub orchestra: OrchestraConfig,
    #[serde(default)]
    pub client: ClientConfig,
    pub agents: AgentsConfig,
    pub outputs: OutputsConfig,
    #[serde(default)]
    pub digitalocean: DigitalOceanConfig,
    #[serde(default)]
    pub notifications: NotificationsConfig,
    #[serde(default)]
    pub logging: LoggingConfig,
    #[serde(default)]
    pub features: FeaturesConfig,
    #[serde(default)]
    pub teams: TeamsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientConfig {
    #[serde(default = "default_client_mode")]
    pub default_mode: String,
}

fn default_client_mode() -> String {
    "claude-code".to_string()
}

impl Default for ClientConfig {
    fn default() -> Self {
        Self {
            default_mode: default_client_mode(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestraConfig {
    pub name: String,
    pub version: String,
    pub default_mode: String,
    #[serde(default)]
    pub schedule: Option<ScheduleConfig>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScheduleConfig {
    pub interval_hours: u32,
    pub max_retries: u32,
    pub retry_delay_seconds: u64,
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
    /// Per-agent client mode override: "api", "claude-code", or "hybrid".
    /// If absent, inherits the global CLIENT_MODE.
    #[serde(default)]
    pub client_mode: Option<String>,
    /// System prompt that gives this agent its identity/role.
    #[serde(default)]
    pub system_prompt: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputsConfig {
    pub directory: String,
    pub retention_days: u32,
    pub formats: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DigitalOceanConfig {
    #[serde(default)]
    pub region: String,
    #[serde(default)]
    pub registry: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NotificationsConfig {
    #[serde(default)]
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoggingConfig {
    #[serde(default = "default_log_level")]
    pub level: String,
    #[serde(default = "default_log_format")]
    pub format: String,
}

fn default_log_level() -> String {
    "INFO".to_string()
}
fn default_log_format() -> String {
    "json".to_string()
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: default_log_level(),
            format: default_log_format(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FeaturesConfig {
    #[serde(default)]
    pub parallel_execution: bool,
    #[serde(default)]
    pub auto_scaling: bool,
    #[serde(default)]
    pub health_monitoring: bool,
}

/// Configuration for Agent Teams integration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TeamsConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_tasks_dir")]
    pub tasks_dir: String,
    #[serde(default = "default_output_prefix")]
    pub output_prefix: String,
    #[serde(default)]
    pub definitions: std::collections::HashMap<String, TeamDefinition>,
}

fn default_tasks_dir() -> String {
    "~/.claude/tasks".to_string()
}

fn default_output_prefix() -> String {
    "teams".to_string()
}

impl Default for TeamsConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            tasks_dir: default_tasks_dir(),
            output_prefix: default_output_prefix(),
            definitions: std::collections::HashMap::new(),
        }
    }
}

/// A team definition with a description and list of teammates.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TeamDefinition {
    pub description: String,
    pub teammates: Vec<TeammateDefinition>,
}

/// A teammate within a team definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TeammateDefinition {
    pub name: String,
    pub role: String,
    #[serde(default = "default_teammate_timeout")]
    pub timeout_seconds: u64,
}

fn default_teammate_timeout() -> u64 {
    300
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
                schedule: None,
            },
            client: ClientConfig::default(),
            agents: AgentsConfig {
                monitor: AgentConfig {
                    enabled: true,
                    timeout_seconds: 120,
                    client_mode: None,
                    system_prompt: None,
                },
                analyzer: AgentConfig {
                    enabled: true,
                    timeout_seconds: 180,
                    client_mode: None,
                    system_prompt: None,
                },
                researcher: AgentConfig {
                    enabled: true,
                    timeout_seconds: 300,
                    client_mode: None,
                    system_prompt: None,
                },
                reporter: AgentConfig {
                    enabled: true,
                    timeout_seconds: 120,
                    client_mode: None,
                    system_prompt: None,
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
            notifications: NotificationsConfig::default(),
            logging: LoggingConfig::default(),
            features: FeaturesConfig::default(),
            teams: TeamsConfig::default(),
        }
    }
}
