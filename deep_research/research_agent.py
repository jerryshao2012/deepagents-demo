import argparse
from datetime import datetime

from deepagents.backends.utils import file_data_to_string
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

        # Sanitize filename
        title = "".join(c for c in title if c.isalnum() or c in ("-", "_")).strip("-").strip("_")
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
    parser = argparse.ArgumentParser(description="Run the Deep Research Agent")
    parser.add_argument("subject", type=str, help="Research subject")
    parser.add_argument("--pdf-folder", type=str,
                        help="Optional folder containing PDF documents to use as research material")
    parser.add_argument("--slides", action="store_true",
                        help="Format the output as a 3-slide PowerPoint training markup")
    parser.add_argument("--title", type=str,
                        help="Optional research title for output file")
    args = parser.parse_args()

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
            # Inspect the latest state change
            msgs = state.get("messages", [])
            files = state.get("files", {})
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
                        print(f"⚙️  Agent is thinking/acting: Calling `{tc_name}`...")
                elif role == "tool":
                    print(f"✅ Executed tool `{name}` successfully (output size: {len(content)} chars)")
                elif role == "ai" and content:
                    print(f"💬 Agent response update...")
                elif role == "human" or role == "user":
                    print(f"🚀 Initializing research inputs...")

            result = state  # The last emitted state is our final result

        print("\n✨ Research completed!\n")
    except Exception as e:
        # Fallback to invoke if stream doesn't work out of the box
        print(f"⚠️ Streaming not fully supported or interrupted ({e}), running normally...")
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
