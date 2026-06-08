# ROS Package [bob_nostr](https://github.com/bob-ros2/bob_nostr)
[![CI](https://github.com/bob-ros2/bob_nostr/actions/workflows/ros2_ci.yml/badge.svg)](https://github.com/bob-ros2/bob_nostr/actions/workflows/ros2_ci.yml)
[![amd64](https://img.shields.io/github/actions/workflow/status/bob-ros2/bob_nostr/docker.yml?label=amd64&logo=docker)](https://github.com/bob-ros2/bob_nostr/actions/workflows/docker.yml)
[![arm64](https://img.shields.io/github/actions/workflow/status/bob-ros2/bob_nostr/docker.yml?label=arm64&logo=docker)](https://github.com/bob-ros2/bob_nostr/actions/workflows/docker.yml)

Minimalist ROS 2 Nostr Agent with autonomous self-evolution capabilities. This package forms the core of an AI assistant operating in a secure, containerized environment.

---
## Getting Started

### 1. Cloning the Repository
Clone the repository recursively to fetch any submodules (if present) and navigate into the project directory:
```bash
git clone https://github.com/bob-ros2/bob_nostr.git
cd bob_nostr
```

### 2. Docker Containerized Run (Recommended)

Docker Compose orchestrates the core brain, the isolated signing service, the API gateway, and the hardened REPL sandbox.

#### Option A: Host Directory Bind Mount (Recommended)
This approach maps a directory on your host filesystem, ensuring that the agent's memories, configurations, and custom skill scripts are persistent across container rebuilds:
1. Prepare your local environment files:
   ```bash
   cp .env.template .env
   cp .env.signer.template .env.signer
   ```
2. Configure `.env` and `.env.signer` with your Nostr keys and backend URLs.
3. Start the Docker containers:
   ```bash
   docker compose -f docker/compose-base.yaml up -d
   ```

#### Option B: Docker Named Volumes (Alternative)
If you prefer not to map host folders to the container, you can use a persistent Docker named volume instead. 
1. In the `compose-base.yaml` file, declare a named volume at the bottom:
   ```yaml
   volumes:
     agent-data:
   ```
2. Map this named volume to the agent's base service instead of the host bind mount:
   ```yaml
   services:
     base:
       ...
       volumes:
         - agent-data:/home/ros/agent
   ```
3. Start the stack normally with `docker compose`.

---

### 3. Bare-Metal Run (Without Docker)

You can run the agent natively on your host system if you have ROS 2 Humble (or compatible version) installed.

1. Ensure you clone the required sibling package dependencies into the `src/` directory of your ROS 2 workspace:
   * **[bob_llm](https://github.com/bob-ros2/bob_llm)**: The core LLM interface node.
   * **[bob_launch](https://github.com/bob-ros2/bob_launch)**: The ROS meta-launcher used to start and configure the agent or other ros nodes.
   ```bash
   cd path/to/your/ros2_ws/src
   git clone https://github.com/bob-ros2/bob_llm.git
   git clone https://github.com/bob-ros2/bob_launch.git
   ```
2. Install the Python dependencies on your host:
   ```bash
   pip3 install -r requirements.txt
   # Also install requirements.txt for bob_llm and bob_launch if not already present.
   ```
3. Build the packages inside your ROS 2 colcon workspace:
   ```bash
   colcon build --packages-select bob_llm bob_launch bob_nostr
   source install/setup.bash
   ```
4. Run the base launch configuration:
   ```bash
   ros2 launch bob_nostr base_launch.yaml
   ```
   *Note: Ensure that the environment variables from `.env` are exported to your shell session before executing the launch command.*

---

## Interacting with the Agent

Once the agent is up and running, you have two main options for interaction:

### A. CLI Chat Mode (via `bob_llm`)
You can interact with the agent locally through a command-line interface. Run the built-in chat client pointing to the agent's ROS 2 topics:
```bash
ros2 run bob_llm chat \
  --topic_in /nostr/llm_prompt \
  --topic_response /nostr/llm_response \
  --topic_out /nostr/llm_stream
```
*(Or run the `chat` alias inside the container's shell session.)*

### B. Nostr Client Chat
The `nostr_client_node` automatically subscribes to mentions (Kind 1) and secure direct messages (Kind 1059 / NIP-17) sent to the agent's public key. 
1. Get the agent's public key (npub) from the log output or the signer config.
2. Send a public mention or an encrypted NIP-17 DM to the agent using any Nostr client (like noStrudel, Primal, or Amethyst).
3. The agent will process the prompt via the local ROS 2 network and reply back directly.

---

## The Nostr Universe

To understand how the agent communicates globally, it helps to understand the underpinnings of the Nostr protocol. 

For a comprehensive overview, visit: **[https://nostr.how/en/what-is-nostr](https://nostr.how/en/what-is-nostr)**

### Nostr Basics
* **Relays**: Relays are independent, open, and stateless servers that accept, store, and distribute events. Clients connect to multiple relays to send and receive updates. Since there is no single central server, the architecture is highly resilient and censorship-resistant.
* **Cryptographic Identity**: There are no usernames or passwords in Nostr. Your identity is a public-private keypair. The public key (hex or `npub` format) acts as your global identity. The private key (hex or `nsec` format) is used to sign events, verifying authorship.
* **Events**: Everything in Nostr is a JSON-formatted event. Different event "Kinds" represent different data types (e.g., Kind 1 for public notes, Kind 1059 for wrapped secure messages).

---

## ROS 2 Architecture & API

For more information about the Robot Operating System, visit: **[https://ros.org/](https://ros.org/)**

The Robot Operating System (ROS 2) coordinates the agent's modular subservices as independent, asynchronous nodes communicating over secure DDS topics.

### Nodes
* **`nostr_bridge`** (`bob_nostr/nostr_client_node.py`): Connects to the configured relays, retrieves incoming events (mentions & DMs), submits signing/decryption calls to the isolated signer service, and publishes prompts to the local ROS 2 network.
* **`repl`** (`bob_nostr/repl_node.py`): Hardened Python REPL runtime. Listens for executable snippets from the agent's brain and executes them in an isolated session.
* **`agent_brain`** (`bob_llm` package): Integrates the LLM context, loads the custom skills list, processes prompts, and orchestrates tool execution.

### Topics
*(All topics are scoped under the configured `ROS_NAMESPACE`, e.g., `/nostr`)*
* **`/nostr/llm_prompt`** (`std_msgs/msg/String`): (Subscribed) Receives user prompts from the Nostr bridge or local CLI.
* **`/nostr/llm_response`** (`std_msgs/msg/String`): (Published) Final, complete response from the LLM brain.
* **`/nostr/llm_stream`** (`std_msgs/msg/String`): (Published) Token-by-token chunks of the streaming response.
* **`/nostr/llm_reasoning`** (`std_msgs/msg/String`): (Published) Live reasoning/thinking content from reasoning models (e.g. DeepSeek-R1).
* **`/nostr/llm_tool_calls`** (`std_msgs/msg/String`): (Published) JSON information detailing executed skills/tools.
* **`/nostr/llm_latest_turn`** (`std_msgs/msg/String`): (Published) Latest conversation turn formatted as a JSON array of messages.
* **`/nostr/llm_stats`** (`std_msgs/msg/String`): (Published) Model execution statistics (token counts, generation speed).
* **`/nostr/repl/input`** (`std_msgs/msg/String`): Executable Python code strings routed to the sandboxed REPL node.
* **`/nostr/repl/output`** (`std_msgs/msg/String`): Standard output, standard error, or traceback returned from the REPL sandbox.
* **`/nostr/repl/status`** (`std_msgs/msg/String`): Periodically published REPL session metadata.

### Parameters
Configured in `launch/base_launch.yaml`:
* **`api_url`**: Endpoint URL for the backend LLM service.
* **`api_model`**: The target LLM model name.
* **`system_prompt_file`**: System configuration markdown containing identity and safety instructions.
* **`skill_dir`**: Comma-separated paths of core and custom skills directories.
