use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::env;
use std::fs;
use std::path::PathBuf;
use tracing::{error, info, warn};

mod agents;
mod client;
mod config;

use agents::{AgentResult, AgentTask};
use client::{create_agent_client, create_client, AgentClient, ClientMode};
use config::Config;

#[derive(Debug, Serialize, Deserialize)]
pub struct OrchestrationResult {
    timestamp: DateTime<Utc>,
    mode: String,
    global_client_mode: String,
    results: Vec<AgentResult>,
}

pub struct Orchestrator {
    global_mode: ClientMode,
    api_key: Option<String>,
    config: Config,
    mode: String,
    timestamp: DateTime<Utc>,
    output_dir: PathBuf,
}

impl Orchestrator {
    pub fn new() -> Result<Self> {
        // Load environment variables
        dotenv::dotenv().ok();

        // Determine client mode (default: claude-code)
        let client_mode_str =
            env::var("CLIENT_MODE").unwrap_or_else(|_| "claude-code".to_string());
        let global_mode = ClientMode::from_str(&client_mode_str)?;

        // API key (required for api/hybrid modes)
        let api_key = env::var("ANTHROPIC_API_KEY").ok();

        // Validate that the global mode can be created (e.g. key present for api/hybrid)
        let _validate = create_client(&global_mode, api_key.clone())?;
        drop(_validate);

        info!("Global client mode: {}", global_mode);

        let mode = env::var("ORCHESTRATOR_MODE").unwrap_or_else(|_| "auto".to_string());

        let timestamp = Utc::now();

        let output_dir = PathBuf::from("outputs");
        fs::create_dir_all(&output_dir).context("Failed to create output directory")?;

        let config = Config::load("config/orchestra.yml").unwrap_or_else(|_| Config::default());

        Ok(Self {
            global_mode,
            api_key,
            config,
            mode,
            timestamp,
            output_dir,
        })
    }

    pub async fn run(&self) -> Result<()> {
        info!("Starting Agent Orchestra - Mode: {}", self.mode);
        info!("Timestamp: {}", self.timestamp.format("%Y%m%d-%H%M%S"));

        let tasks = self.get_agent_tasks();
        info!("Running {} agents", tasks.len());

        let results = if self.config.features.parallel_execution {
            info!("Parallel execution enabled");
            self.run_parallel(tasks).await
        } else {
            self.run_sequential(tasks).await
        };

        self.save_results(&results)?;
        self.generate_summary(&results)?;

        info!("Orchestration complete!");
        Ok(())
    }

    /// Run agents one at a time (original behaviour).
    async fn run_sequential(&self, tasks: Vec<AgentTask>) -> Vec<AgentResult> {
        let mut results = Vec::new();
        for task in tasks {
            let agent_name = task.name.clone();
            let mode_label = task
                .client_mode
                .as_deref()
                .unwrap_or(&self.global_mode.to_string())
                .to_string();

            match self.run_agent(task).await {
                Ok(result) => results.push(result),
                Err(e) => {
                    error!("Agent execution failed: {:?}", e);
                    results.push(AgentResult::failed(
                        agent_name,
                        format!("{:?}", e),
                        mode_label,
                    ));
                }
            }

            // Small delay between agents
            tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
        }
        results
    }

    /// Run all agents concurrently via tokio::spawn.
    async fn run_parallel(&self, tasks: Vec<AgentTask>) -> Vec<AgentResult> {
        let mut handles = Vec::new();

        for task in tasks {
            let agent_name = task.name.clone();
            let mode_label = task
                .client_mode
                .as_deref()
                .unwrap_or(&self.global_mode.to_string())
                .to_string();
            let global_mode = self.global_mode.clone();
            let api_key = self.api_key.clone();

            // Each spawned task gets its own client
            let client: Box<dyn AgentClient> = match create_agent_client(
                task.client_mode.as_deref(),
                &global_mode,
                api_key,
            ) {
                Ok(c) => c,
                Err(e) => {
                    handles.push(tokio::spawn(async move {
                        AgentResult::failed(agent_name, format!("{:?}", e), mode_label)
                    }));
                    continue;
                }
            };

            let timeout_secs = task.timeout_seconds;
            let prompt = task.prompt.clone();
            let system_prompt = task.system_prompt.clone();

            handles.push(tokio::spawn(async move {
                info!("Running agent: {} (timeout: {}s)", agent_name, timeout_secs);
                let timeout = std::time::Duration::from_secs(timeout_secs);
                match tokio::time::timeout(
                    timeout,
                    client.send_message(&prompt, system_prompt.as_deref()),
                )
                .await
                {
                    Ok(Ok(response)) => {
                        info!("Agent {} completed", agent_name);
                        AgentResult::success(agent_name, response, mode_label)
                    }
                    Ok(Err(e)) => {
                        error!("Agent {} failed: {:?}", agent_name, e);
                        AgentResult::failed(agent_name, format!("{:?}", e), mode_label)
                    }
                    Err(_) => {
                        error!("Agent {} timed out after {}s", agent_name, timeout_secs);
                        AgentResult::failed(
                            agent_name,
                            format!("Timed out after {}s", timeout_secs),
                            mode_label,
                        )
                    }
                }
            }));
        }

        let mut results = Vec::new();
        for handle in handles {
            match handle.await {
                Ok(result) => results.push(result),
                Err(e) => error!("Task join error: {:?}", e),
            }
        }
        results
    }

    async fn run_agent(&self, task: AgentTask) -> Result<AgentResult> {
        info!(
            "Running agent: {} (timeout: {}s)",
            task.name, task.timeout_seconds
        );

        let mode_label = task
            .client_mode
            .as_deref()
            .unwrap_or(&self.global_mode.to_string())
            .to_string();

        let client = create_agent_client(
            task.client_mode.as_deref(),
            &self.global_mode,
            self.api_key.clone(),
        )?;

        let timeout = std::time::Duration::from_secs(task.timeout_seconds);
        let response = tokio::time::timeout(
            timeout,
            client.send_message(&task.prompt, task.system_prompt.as_deref()),
        )
        .await
        .context(format!(
            "Agent {} timed out after {}s",
            task.name, task.timeout_seconds
        ))?
        .context("Failed to send message to Claude")?;

        info!("Agent {} completed", task.name);

        Ok(AgentResult::success(task.name, response, mode_label))
    }

    fn get_agent_tasks(&self) -> Vec<AgentTask> {
        let agents = &self.config.agents;

        let filter = |name: &str, prompt: &str| -> Option<AgentTask> {
            let agent_config = match name {
                "monitor" | "health_checker" => &agents.monitor,
                "analyzer" | "data_analyst" | "synthesizer" => &agents.analyzer,
                "researcher" => &agents.researcher,
                "reporter" | "alert_manager" => &agents.reporter,
                _ => {
                    return Some(AgentTask::new(name, prompt, 120));
                }
            };
            if agent_config.enabled {
                Some(
                    AgentTask::new(name, prompt, agent_config.timeout_seconds)
                        .with_client_mode(agent_config.client_mode.clone())
                        .with_system_prompt(agent_config.system_prompt.clone()),
                )
            } else {
                warn!("Skipping disabled agent: {}", name);
                None
            }
        };

        let tasks: Vec<AgentTask> = match self.mode.as_str() {
            "auto" => vec![
                filter(
                    "monitor",
                    "Check system health, review logs, and identify any issues that need attention. Provide a brief status report.",
                ),
                filter(
                    "analyzer",
                    "Analyze recent activity patterns and suggest optimizations or improvements for the system.",
                ),
            ],
            "research" => vec![
                filter(
                    "researcher",
                    "Research the latest developments in AI agent orchestration and multi-agent systems. Summarize key findings.",
                ),
                filter(
                    "synthesizer",
                    "Based on current trends, suggest improvements to our agent orchestration framework.",
                ),
            ],
            "analysis" => vec![
                filter(
                    "data_analyst",
                    "Analyze system performance metrics and identify bottlenecks or areas for improvement.",
                ),
                filter(
                    "reporter",
                    "Generate a comprehensive report on system status and recommendations.",
                ),
            ],
            "monitoring" => vec![
                filter(
                    "health_checker",
                    "Perform comprehensive health checks on all system components and services.",
                ),
                filter(
                    "alert_manager",
                    "Review recent alerts and events, prioritize issues, and suggest actions.",
                ),
            ],
            _ => {
                warn!("Unknown mode '{}', using 'auto'", self.mode);
                vec![
                    filter(
                        "monitor",
                        "Check system health, review logs, and identify any issues that need attention. Provide a brief status report.",
                    ),
                    filter(
                        "analyzer",
                        "Analyze recent activity patterns and suggest optimizations or improvements for the system.",
                    ),
                ]
            }
        }
        .into_iter()
        .flatten()
        .collect();

        if tasks.is_empty() {
            warn!("All agents disabled for mode '{}'", self.mode);
        }
        tasks
    }

    fn save_results(&self, results: &[AgentResult]) -> Result<()> {
        let timestamp_str = self.timestamp.format("%Y%m%d-%H%M%S").to_string();
        let output_file = self
            .output_dir
            .join(format!("results-{}.json", timestamp_str));

        let orchestration = OrchestrationResult {
            timestamp: self.timestamp,
            mode: self.mode.clone(),
            global_client_mode: self.global_mode.to_string(),
            results: results.to_vec(),
        };

        let json =
            serde_json::to_string_pretty(&orchestration).context("Failed to serialize results")?;

        fs::write(&output_file, json).context("Failed to write results file")?;

        info!("Results saved to {}", output_file.display());
        Ok(())
    }

    fn generate_summary(&self, results: &[AgentResult]) -> Result<()> {
        let timestamp_str = self.timestamp.format("%Y%m%d-%H%M%S").to_string();
        let summary_file = self
            .output_dir
            .join(format!("summary-{}.txt", timestamp_str));

        let successful = results.iter().filter(|r| r.status == "success").count();
        let failed = results.len() - successful;

        let mut summary = String::new();
        summary.push_str("Agent Orchestra Run Summary\n");
        summary.push_str("==================================================\n\n");
        summary.push_str(&format!("Timestamp: {}\n", timestamp_str));
        summary.push_str(&format!("Mode: {}\n", self.mode));
        summary.push_str(&format!("Global Client: {}\n", self.global_mode));
        summary.push_str(&format!(
            "Parallel: {}\n",
            self.config.features.parallel_execution
        ));
        summary.push_str(&format!("Total Agents: {}\n", results.len()));
        summary.push_str(&format!("Successful: {}\n", successful));
        summary.push_str(&format!("Failed: {}\n\n", failed));

        for result in results {
            summary.push_str("\n──────────────────────────────────────────────────\n");
            summary.push_str(&format!("Agent: {}\n", result.agent));
            summary.push_str(&format!("Status: {}\n", result.status));
            summary.push_str(&format!("Client: {}\n", result.client_mode));

            if result.status == "success" {
                if let Some(ref output) = result.output {
                    summary.push_str(&format!("Output:\n{}\n", output));
                }
            } else if let Some(ref error) = result.error {
                summary.push_str(&format!("Error: {}\n", error));
            }
        }

        fs::write(&summary_file, summary).context("Failed to write summary file")?;

        info!("Summary saved to {}", summary_file.display());
        Ok(())
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("agent_orchestra=info".parse().unwrap()),
        )
        .init();

    let orchestrator = Orchestrator::new()?;
    orchestrator.run().await?;

    Ok(())
}
