import argparse
import itertools
import re
import sys
import threading
import time
from datetime import datetime

from deepagents.backends.utils import file_data_to_string


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    if v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    raise argparse.ArgumentTypeError('Boolean value expected.')


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


from langchain_core.messages import HumanMessage

from agent import agent, model


def generate_research_title(research_content):
    """Generate a concise title for the research content using the configured LLM."""
    try:
        if isinstance(research_content, dict):
            content_snippet = research_content.get("content", "")[:2000]
        else:
            content_snippet = str(research_content)[:2000]

        prompt = (
            "Based on the following research content, generate a short, concise, and descriptive "
            "file name (maximum 5 words, without extension). Return ONLY the file name, using "
            "kebab-case or snake_case for spacing. No quotes, no extra text:\\n\\n"
            f"{content_snippet}"
        )

        response = model.invoke([HumanMessage(content=prompt)])
        title = response.content.strip()

        # Capitalize words in the title
        title = title.title()
        # Sanitize filename: replace spaces with underscores, preserve existing underscores,
        # and only allow alphanumeric characters, hyphens, and underscores
        title = re.sub(r'[^w\-]', '_', title)
        # Collapse multiple consecutive underscores into a single one and trim edges
        title = re.sub(r'_+', '_', title).strip('_')
        return title if title else "research-report"
    except Exception as e:
        print(f"Warning: Could not generate title ({e}). Using default.")
        return "research-report"


def save_research_to_file(research_content, filename=None):
    # Get current date
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Generate a title for the research
    title = generate_research_title(research_content)

    # If filename is not provided, use the generated title as the filename
    if not filename:
        filename = f"{title}-{current_date}.md"

    # Extract string content if a dictionary message was passed
    if isinstance(research_content, dict):
        research_content = research_content.get("content", str(research_content))

    # Write the research content to the file
    with open(filename, "w") as file:
        file.write(research_content)

    return filename


def main():
    parser = argparse.ArgumentParser(description="Run the Deep Research Agent", add_help=False)
    parser.add_argument("subject", type=str, help="Research subject")
    parser.add_argument('--verbose', type=str2bool, nargs='?', const='True', default='True',
                        help='Show progress (default: True). When False, runs agent without progress display')
    parser.add_argument('--help', '-h', action='store_true', help='Show this help message and exit')
    parser.add_argument("--pdf-folder", type=str,
                        help="Optional folder containing PDF documents to use as research material")
    parser.add_argument("--slides", action="store_true",
                        help="Format the output as a 3-slide PowerPoint training markup")
    parser.add_argument("--title", type=str,
                        help="Optional research title for output file")
    args = parser.parse_args()

    if args.help:
        parser.print_help()
        sys.exit(0)

    # Construct the instruction
    instruction = f"Research the following subject: {args.subject}"
    title = None

    if args.pdf_folder:
        instruction += f"\n\nPlease use the 'read_pdf_folder' tool to read PDFs from this folder: '{args.pdf_folder}'."

    if args.slides:
        instruction += "\n\nPlease use the 'generate_slide_markup' tool to output a 3-slide presentation training markup based on your findings."

    if args.title:
        title = args.title

    print(f"Starting research on: {args.subject}")
    print("This may take a few minutes as the agent searches and analyzes...")

    # Run the agent with progress printouts
    result = None
    start_time = time.time()
    last_time = start_time

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
                    stream_mode="values"
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
            })

        total_time = time.time() - start_time
        print(f"\n✨ Research completed in {total_time:.1f}s!\n")

    # Output the result. The agent usually writes to /final_report.md
    files = result.get("files", {})
    if "/final_report.md" in files:
        file_content = file_data_to_string(files['/final_report.md'])
        filename = save_research_to_file(file_content, title)

        print("\n" + "=" * 80)
        print(f"Final Report ({filename}):")
        print("=" * 80)
        print(file_content)
    else:
        # Fallback to the last message content
        last_message = result.get('messages', [])[-1]
        filename = save_research_to_file(last_message, title)

        print("\n" + "=" * 80)
        print(f"Final Response ({filename}):")
        print("=" * 80)
        print(last_message.get('content', 'No output received.'))


if __name__ == "__main__":
    main()
