import itertools
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from deepagents.backends.utils import file_data_to_string
from dotenv import load_dotenv

from utils import str2bool, get_ssl_verify_config

# Load environment variables
load_dotenv()


class Spinner:
    def __init__(self, message="Working..."):
        self.spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self.stop_running = threading.Event()
        self.thread = None
        self.message = message

    def spin(self):
        while not self.stop_running.is_set():
            sys.stdout.write(f"\r\033[K\033[36m{next(self.spinner)}\033[0m {self.message}")
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self, message=None):
        if message:
            self.message = message
        self.stop_running.clear()
        self.thread = threading.Thread(target=self.spin)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.stop_running.set()
        if self.thread and self.thread.is_alive():
            self.thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


from langchain_core.messages import BaseMessage, HumanMessage

from agent import agent, model
from research_agent.cli import build_instruction, build_parser, list_targets
from research_agent.tools import trigger_dataset_evaluation


CSV_EXPORT_PATH_RE = re.compile(r"\*\*CSV exported to:\*\*\s*`([^`]+)`")


def generate_research_title(research_content):
    """Generate a concise title for the research content using the configured LLM."""
    try:
        content_snippet = extract_message_content(research_content)[:2000]

        prompt = (
            "Based on the following research content, generate a short, concise, and descriptive "
            "file name (maximum 5 words, without extension). Return ONLY the file name, using "
            "kebab-case or snake_case for spacing. No quotes, no extra text:\\n\\n"
            f"{content_snippet}"
        )

        response = model.invoke([HumanMessage(content=prompt)])
        title = response.content.strip()

        # Format title with underscores and proper capitalization
        title = title.replace(" ", "_").title()  # Replace spaces with underscores first
        title = ''.join(
            [c if c.isalnum() or c == '_' else '_' for c in title])  # Replace special characters with underscores
        title = re.sub(r'_+', '_', title)  # Replace multiple underscores with single
        title = title.strip('_')  # Remove leading/trailing underscores
        return title if title else "research-report"
    except Exception as e:
        print(f"Warning: Could not generate title ({e}). Using default.")
        return "research-report"


def extract_message_content(message):
    """Normalize agent output into plain text for saving and display."""
    if isinstance(message, dict):
        content = message.get("content", "")
    elif isinstance(message, BaseMessage):
        content = message.content
    else:
        content = message

    if isinstance(content, list):
        normalized_parts = []
        for item in content:
            if isinstance(item, str):
                normalized_parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or str(item)
                normalized_parts.append(text)
            else:
                normalized_parts.append(str(item))
        return "\n".join(part for part in normalized_parts if part)

    return str(content)


def save_research_to_file(research_content, filename=None, output_folder=None):
    # Get current date
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Generate a title for the research
    title = generate_research_title(research_content)

    # If filename is not provided, use the generated title as the filename
    if not filename:
        filename = f"{title}-{current_date}.md"

    # Extract string content if a dictionary message was passed
    research_content = extract_message_content(research_content)

    # Determine the full path for the file
    if output_folder:
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / filename
    else:
        file_path = Path(filename)

    # Write the research content to the file
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(research_content)

    return str(file_path)


def derive_output_folder(doc_folder: str | None) -> Path | None:
    if not doc_folder:
        return None
    return Path("output") / Path(doc_folder).name


def run_dataset_evaluation(file_path: str) -> str:
    return trigger_dataset_evaluation.invoke({"file_path": file_path})


def append_dataset_evaluation_result(research_content: str) -> str:
    match = CSV_EXPORT_PATH_RE.search(research_content)
    if not match:
        return research_content

    csv_path = match.group(1).strip()
    evaluation_result = run_dataset_evaluation(csv_path)
    if evaluation_result in research_content:
        return research_content
    return research_content.rstrip() + f"\n\n**Dataset evaluation:** {evaluation_result}\n"


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.verify_ssl = str2bool(args.verify_ssl)
    args.verbose = str2bool(args.verbose)

    if args.help:
        parser.print_help()
        sys.exit(0)

    if args.target == "list":
        list_targets()
        sys.exit(0)

    target = args.target
    instruction = build_instruction(
        args.subject,
        doc_folder=args.doc_folder,
        target=target,
        subject_file=args.subject_file,
        no_web=args.no_web,
    )
    title = None

    if args.title:
        title = args.title

    print(f"Starting research on: {args.subject}")
    print("This may take a few minutes as the agent searches and analyzes...")

    # Run the agent with progress printouts
    result = None
    start_time = time.time()
    last_time = start_time

    # Create SSL verification setting - CLI flag takes precedence over env var
    verify_ssl = get_ssl_verify_config()
    print(f"SSL Verification is set to: {verify_ssl}")

    # Run the agent based on verbose flag
    if args.verbose:
        # Show progress with spinner
        spinner = Spinner("Initializing research inputs...")
        spinner.start()

        try:
            # We attempt to stream updates from LangGraph to provide visibility
            for state in agent.stream(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": instruction,
                            }
                        ],
                    },
                    stream_mode="values",
                    verify_ssl=verify_ssl
            ):
                current_time = time.time()
                step_time = current_time - last_time
                last_time = current_time

                spinner.stop()

                # Inspect the latest state change
                msgs = state.get("messages", [])
                files = state.get("files", {})
                next_spinner_msg = "Agent is working..."

                if msgs:
                    last = msgs[-1]
                    # Handle both dict-based and object-based messages
                    if isinstance(last, dict):
                        role = last.get("role", "")
                        content = str(last.get("content", ""))
                        name = last.get("name", "")
                        tool_calls = last.get("tool_calls", [])
                    else:
                        role = getattr(last, "type", "")
                        content = str(getattr(last, "content", ""))
                        name = getattr(last, "name", "")
                        tool_calls = getattr(last, "tool_calls", [])

                    # Output meaningful progress based on the last message type
                    if role == "ai" and tool_calls:
                        for tc in tool_calls:
                            tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
                            print(f"⚙️  Agent decided to act: Calling `{tc_name}`... (⏱️  {step_time:.1f}s)")
                            next_spinner_msg = f"Executing `{tc_name}`..."
                    elif role == "tool":
                        print(
                            f"✅ Executed tool `{name}` successfully (output size: {len(content)} chars) (⏱️  {step_time:.1f}s)")
                        next_spinner_msg = "Analyzing tool output..."
                    elif role == "ai" and content:
                        print(f"💬 Agent updated its response based on findings... (⏱️  {step_time:.1f}s)")
                        next_spinner_msg = "Structuring final thoughts..."
                    elif role == "human" or role == "user":
                        print(f"🚀 Started research task... (⏱️  {step_time:.1f}s)")
                        next_spinner_msg = "Agent is formulating a plan..."

                result = state  # The last emitted state is our final result
                spinner.start(next_spinner_msg)

            spinner.stop()
            total_time = time.time() - start_time
            print(f"\n✨ Research completed in {total_time:.1f}s!\n")
        except Exception as e:
            spinner.stop()
            total_time = time.time() - start_time
            # Fallback to invoke if stream doesn't work out of the box
            print(
                f"⚠️ Streaming not fully supported or interrupted ({e}), running normally... (failed after {total_time:.1f}s)")

            spinner.start("Running fallback synchronous invoke...")
            start_invoke = time.time()
            result = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": instruction,
                        }
                    ],
                },
                verify_ssl=verify_ssl
            )
            spinner.stop()
            invoke_time = time.time() - start_invoke
            print(f"\n✨ Fallback research completed in {invoke_time:.1f}s!\n")
    else:
        # Run the agent directly without showing progress
        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": instruction,
                    }
                ],
            },
            verify_ssl=verify_ssl
        )
        total_time = time.time() - start_time
        print(f"\n✨ Research completed in {total_time:.1f}s!\n")

    # Output the result. The agent usually writes to /final_report.md
    files = result.get("files", {})

    # Determine output folder for final response
    output_folder = derive_output_folder(args.doc_folder)

    if "/final_report.md" in files:
        file_content = file_data_to_string(files['/final_report.md'])
        file_content = append_dataset_evaluation_result(file_content)
        filename = save_research_to_file(file_content, title, output_folder=output_folder)

        print("\n" + "=" * 80)
        print(f"Final Report ({filename}):")
        print("=" * 80)
        print(file_content)
    else:
        # Fallback to the last message content
        last_message = result.get('messages', [])[-1]
        last_message_content = extract_message_content(last_message)
        last_message_content = append_dataset_evaluation_result(last_message_content)
        filename = save_research_to_file(last_message_content, title, output_folder=output_folder)

        print("\n" + "=" * 80)
        print(f"Final Response ({filename}):")
        print("=" * 80)
        print(last_message_content or 'No output received.')


if __name__ == "__main__":
    main()
