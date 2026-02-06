use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::env;
use std::fs;
use std::path::PathBuf;
use chrono::{DateTime, Utc};
use tracing::{info, error, warn};

mod agents;
mod client;
mod config;

use agents::{AgentTask, AgentResult};
use client::ClaudeClient;
use config::Config;

#[derive(Debug, Serialize, Deserialize)]
pub struct OrchestrationResult {
    timestamp: DateTime<Utc>,
    mode: String,
    results: Vec<AgentResult>,
}

pub struct Orchestrator {
    client: ClaudeClient,
    config: Config,
    mode: String,
    timestamp: DateTime<Utc>,
    output_dir: PathBuf,
}

impl Orchestrator {
    pub fn new() -> Result<Self> {
        // Load environment variables
        dotenv::dotenv().ok();

        let api_key = env::var("ANTHROPIC_API_KEY")
            .context("ANTHROPIC_API_KEY must be set")?;
        
        let mode = env::var("ORCHESTRATOR_MODE")
            .unwrap_or_else(|_| "auto".to_string());
        
        let timestamp = Utc::now();
        
        let output_dir = PathBuf::from("outputs");
        fs::create_dir_all(&output_dir)
            .context("Failed to create output directory")?;

        let config = Config::load("config/orchestra.yml")
            .unwrap_or_else(|_| Config::default());

        Ok(Self {
            client: ClaudeClient::new(api_key),
            config,
            mode,
            timestamp,
            output_dir,
        })
    }

    pub async fn run(&self) -> Result<()> {
        info!("🎭 Starting Agent Orchestra - Mode: {}", self.mode);
        info!("📅 Timestamp: {}", self.timestamp.format("%Y%m%d-%H%M%S"));

        let tasks = self.get_agent_tasks();
        info!("📋 Running {} agents", tasks.len());

        let mut results = Vec::new();

        // Run agents sequentially
        for task in tasks {
            let agent_name = task.name.clone();
            match self.run_agent(task).await {
                Ok(result) => results.push(result),
                Err(e) => {
                    error!("Agent execution failed: {}", e);
                    results.push(AgentResult::failed(agent_name, e.to_string()));
                }
            }
            
            // Small delay between agents
            tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
        }

        self.save_results(&results)?;
        self.generate_summary(&results)?;

        info!("🎉 Orchestration complete!");
        Ok(())
    }

    async fn run_agent(&self, task: AgentTask) -> Result<AgentResult> {
        info!("🤖 Running agent: {}", task.name);

        let response = self.client.send_message(&task.prompt).await
            .context("Failed to send message to Claude")?;

        info!("✅ Agent {} completed", task.name);

        Ok(AgentResult::success(task.name, response))
    }

    fn get_agent_tasks(&self) -> Vec<AgentTask> {
        match self.mode.as_str() {
            "auto" => vec![
                AgentTask::new(
                    "monitor",
                    "Check system health, review logs, and identify any issues that need attention. Provide a brief status report."
                ),
                AgentTask::new(
                    "analyzer",
                    "Analyze recent activity patterns and suggest optimizations or improvements for the system."
                ),
            ],
            "research" => vec![
                AgentTask::new(
                    "researcher",
                    "Research the latest developments in AI agent orchestration and multi-agent systems. Summarize key findings."
                ),
                AgentTask::new(
                    "synthesizer",
                    "Based on current trends, suggest improvements to our agent orchestration framework."
                ),
            ],
            "analysis" => vec![
                AgentTask::new(
                    "data_analyst",
                    "Analyze system performance metrics and identify bottlenecks or areas for improvement."
                ),
                AgentTask::new(
                    "reporter",
                    "Generate a comprehensive report on system status and recommendations."
                ),
            ],
            "monitoring" => vec![
                AgentTask::new(
                    "health_checker",
                    "Perform comprehensive health checks on all system components and services."
                ),
                AgentTask::new(
                    "alert_manager",
                    "Review recent alerts and events, prioritize issues, and suggest actions."
                ),
            ],
            _ => {
                warn!("Unknown mode '{}', using 'auto'", self.mode);
                vec![
                    AgentTask::new(
                        "monitor",
                        "Check system health, review logs, and identify any issues that need attention. Provide a brief status report.",
                    ),
                    AgentTask::new(
                        "analyzer",
                        "Analyze recent activity patterns and suggest optimizations or improvements for the system.",
                    ),
                ]
            }
        }
    }

    fn save_results(&self, results: &[AgentResult]) -> Result<()> {
        let timestamp_str = self.timestamp.format("%Y%m%d-%H%M%S").to_string();
        let output_file = self.output_dir.join(format!("results-{}.json", timestamp_str));

        let orchestration = OrchestrationResult {
            timestamp: self.timestamp,
            mode: self.mode.clone(),
            results: results.to_vec(),
        };

        let json = serde_json::to_string_pretty(&orchestration)
            .context("Failed to serialize results")?;

        fs::write(&output_file, json)
            .context("Failed to write results file")?;

        info!("💾 Results saved to {}", output_file.display());
        Ok(())
    }

    fn generate_summary(&self, results: &[AgentResult]) -> Result<()> {
        let timestamp_str = self.timestamp.format("%Y%m%d-%H%M%S").to_string();
        let summary_file = self.output_dir.join(format!("summary-{}.txt", timestamp_str));

        let successful = results.iter().filter(|r| r.status == "success").count();
        let failed = results.len() - successful;

        let mut summary = String::new();
        summary.push_str("Agent Orchestra Run Summary\n");
        summary.push_str("==================================================\n\n");
        summary.push_str(&format!("Timestamp: {}\n", timestamp_str));
        summary.push_str(&format!("Mode: {}\n", self.mode));
        summary.push_str(&format!("Total Agents: {}\n", results.len()));
        summary.push_str(&format!("Successful: {}\n", successful));
        summary.push_str(&format!("Failed: {}\n\n", failed));

        for result in results {
            summary.push_str("\n──────────────────────────────────────────────────\n");
            summary.push_str(&format!("Agent: {}\n", result.agent));
            summary.push_str(&format!("Status: {}\n", result.status));
            
            if result.status == "success" {
                if let Some(ref output) = result.output {
                    summary.push_str(&format!("Output:\n{}\n", output));
                }
            } else if let Some(ref error) = result.error {
                summary.push_str(&format!("Error: {}\n", error));
            }
        }

        fs::write(&summary_file, summary)
            .context("Failed to write summary file")?;

        info!("📊 Summary saved to {}", summary_file.display());
        Ok(())
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("agent_orchestra=info".parse().unwrap())
        )
        .init();

    let orchestrator = Orchestrator::new()?;
    orchestrator.run().await?;

    Ok(())
}
