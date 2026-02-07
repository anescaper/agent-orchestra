# Multi-stage build for minimal final image

# Stage 1: Builder
FROM rust:1.75-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy manifests
COPY Cargo.toml Cargo.lock ./

# Create dummy main to cache dependencies
RUN mkdir src && \
    echo "fn main() {}" > src/main.rs && \
    cargo build --release && \
    rm -rf src

# Copy actual source code
COPY src ./src
COPY config ./config

# Build the application
RUN cargo build --release

# Stage 2: Runtime
FROM debian:bookworm-slim

WORKDIR /app

# Install runtime dependencies + Node.js (for claude CLI in hybrid/claude-code mode)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install claude CLI globally (used by claude-code and hybrid modes)
RUN npm install -g @anthropic-ai/claude-code 2>/dev/null || true

# Copy the binary from builder
COPY --from=builder /app/target/release/agent-orchestra /app/agent-orchestra

# Copy config
COPY config ./config

# Create outputs directory
RUN mkdir -p outputs

# Set environment
ENV RUST_LOG=info
# Default to hybrid mode; override with CLIENT_MODE env var
ENV CLIENT_MODE=hybrid

# Run the application
CMD ["/app/agent-orchestra"]
