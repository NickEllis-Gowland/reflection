import gradio as gr
import os
import re
import json
from datetime import datetime
from typing import Optional, List, Any, Dict, Tuple
from cot_reflection_file import (
    cot_reflection, 
    cot_prompt as default_cot_prompt, 
    system_prompt as default_system_prompt,
    get_model_response,
    AVAILABLE_MODELS
)
from document_utils import read_document
from db_utils import SnapshotDB
import PyPDF2
from docx import Document

# Initialize database
db = SnapshotDB()

def get_available_models() -> List[str]:
    """
    Get list of available models.
    
    Returns:
        List of model names
    """
    return list(AVAILABLE_MODELS.keys())

def process_question(file, user_prompt, system_prompt, cot_prompt, selected_model, use_default_cot):
    """
    Process user question using selected model and prompts.
    
    Args:
        file: Optional document file
        user_prompt: User's question
        system_prompt: System context (can be default or customized)
        cot_prompt: Chain of thought prompt (can be default or customized)
        selected_model: Name of selected model
        use_default_cot: Boolean indicating if CoT processing should be used
        
    Returns:
        Tuple of processed outputs
    """
    try:
        # Validate model selection
        if selected_model not in AVAILABLE_MODELS:
            raise ValueError(f"Invalid model selected: {selected_model}")
            
        # Read document content if file is provided
        document_content = None
        if file is not None:
            try:
                import io
                file_obj = io.BytesIO(file)
                
                try:
                    pdf_reader = PyPDF2.PdfReader(file_obj)
                    document_content = '\n'.join(page.extract_text() for page in pdf_reader.pages)
                except:
                    file_obj.seek(0)
                    doc = Document(file_obj)
                    document_content = '\n'.join(paragraph.text for paragraph in doc.paragraphs)
            except Exception as e:
                raise ValueError("Error reading document. Please ensure it's a valid PDF or DOCX file.")

        # Prepare document content string if document was provided
        doc_content = f"Document Content:\n{document_content}\n\n" if document_content else ""
        
        if use_default_cot:
            # Generate initial response without reasoning
            initial_response_prompt = (f"{system_prompt}\n\n{doc_content}"
                                     f"Question: {user_prompt}\n\n"
                                     "Provide a concise answer to this question without any explanation or reasoning.")
            initial_response = get_model_response(selected_model, initial_response_prompt)
            
            # Use CoT processing with the current cot_prompt (either default or customized)
            thinking, reflection, output = cot_reflection(
                system_prompt=system_prompt,
                cot_prompt=cot_prompt,  # This will be either default or customized version
                question=user_prompt,
                document_content=document_content,
                model_name=selected_model
            )

            # Extract the actual thinking content
            thinking_match = re.search(r'<thinking>(.*?)</thinking>', thinking, re.DOTALL)
            actual_thinking = thinking_match.group(1).strip() if thinking_match else thinking

            # Return full CoT processing results
            return user_prompt, initial_response, actual_thinking, reflection, output, system_prompt, cot_prompt
            
        else:
            # When use_default_cot is False, only use system prompt without CoT
            direct_response_prompt = (f"{system_prompt}\n\n{doc_content}"
                                    f"Question: {user_prompt}\n\n"
                                    "Analyze the question and provide a comprehensive answer.")
            
            direct_response = get_model_response(selected_model, direct_response_prompt)
            
            # Return response without CoT components
            return user_prompt, direct_response, "", "", "", system_prompt, None

    except Exception as e:
        return user_prompt, f"An error occurred: {str(e)}", "", "", "", None, None

def load_snapshot_by_id(snapshot_id: str) -> List[Optional[Any]]:
    """
    Load a snapshot by ID and update UI components.
    
    Args:
        snapshot_id: ID of the snapshot to load
        
    Returns:
        List of values for Gradio components in correct order:
        [snapshot_name, user_prompt, system_prompt, model_name, cot_prompt,
         initial_response, thinking, reflection, final_response, status_message]
    """
    try:
        if not snapshot_id:
            return [None] * 9 + ["Please enter a snapshot ID to load"]
        
        try:
            snapshot_id_int = int(snapshot_id)
        except ValueError:
            return [None] * 9 + ["Invalid Snapshot ID. Please enter a numeric ID."]
        
        # Get snapshot data from database
        snapshot_data = db.get_snapshot_by_id(snapshot_id_int)
        
        if not snapshot_data:
            return [None] * 9 + ["Snapshot not found"]
            
        # Extract values from snapshot data
        return [
            snapshot_data.get("snapshot_name", ""),          # Snapshot name
            snapshot_data.get("user_prompt", ""),            # User prompt
            snapshot_data.get("system_prompt", ""),          # System prompt
            snapshot_data.get("model_name", ""),             # Model name
            snapshot_data.get("cot_prompt", ""),             # Chain of thought prompt
            snapshot_data.get("initial_response", ""),       # Initial response
            snapshot_data.get("thinking", ""),               # Thinking process
            snapshot_data.get("reflection", ""),             # Reflection
            snapshot_data.get("final_response", ""),         # Final response
            "✓ Snapshot loaded successfully"                 # Status message
        ]
    except Exception as e:
        return [None] * 9 + [f"Error loading snapshot: {str(e)}"]

def update_snapshots_table(search_term: str = "") -> List[List]:
    """
    Update the snapshots table with filtered results.
    Returns data in the format: [ID, Name, Created At, Model, Prompt, Tags]
    """
    snapshots = db.get_snapshots(search_term)
    return [[s[0], s[1], s[2], s[3], s[4], s[5]] for s in snapshots]

def export_snapshot(snapshot_id: int) -> str:
    """
    Export a single snapshot as JSON and return its content.
    
    Args:
        snapshot_id: ID of the snapshot to export
        
    Returns:
        JSON string of the snapshot content
    """
    try:
        if not snapshot_id:
            return "Please enter a snapshot ID to export"
            
        # Get snapshot data from database
        snapshot_data = db.get_snapshot_by_id(int(snapshot_id))
        
        if not snapshot_data:
            return "Snapshot not found"
            
        # Convert snapshot to formatted JSON string
        json_content = json.dumps(snapshot_data, indent=2, ensure_ascii=False)
        
        # Return JSON content to be displayed in popup
        return json_content
        
    except Exception as e:
        return f"Error exporting snapshot: {str(e)}"

# Gradio interface
with gr.Blocks(theme=gr.themes.Soft()) as iface:
    with gr.Tabs():
        # Analysis Tab
        with gr.TabItem("Analysis"):
            with gr.Row():
                with gr.Column():
                    model_selector = gr.Dropdown(
                        choices=get_available_models(),
                        value="Gemini 2.0 Flash",
                        label="Select Model",
                        interactive=True,
                        info="Choose from the dropdown menu of the available LLMs"
                    )
                    
                    file_input = gr.File(
                        label="Upload Document",
                        file_types=["pdf", "docx"],
                        type="binary"
                    )
                    
                    user_prompt = gr.Textbox(
                        lines=2,
                        label="User Prompt",
                        placeholder="Ask a question about the uploaded document..."
                    )
                    
                    use_default_cot = gr.Checkbox(
                        label="Use Default Chain of Thought Prompt",
                        value=False
                    )
                    
                    submit_btn = gr.Button("Submit", variant="primary")
                    
                    with gr.Accordion("System and Chain-of-Thought Prompts", open=False):
                        system_prompt = gr.Textbox(
                            lines=2,
                            label="System Prompt",
                            value=default_system_prompt
                        )
                        cot_prompt = gr.Textbox(
                            lines=4,
                            label="Chain of Thought Prompt",
                            value=default_cot_prompt
                        )

            with gr.Row():
                user_prompt_output = gr.Textbox(label="1. User Prompt")
                initial_response_output = gr.Textbox(label="2. Initial Response")
                thinking_output = gr.Textbox(label="3. Thinking")
                reflection_output = gr.Textbox(label="4. Reflection")
                final_output = gr.Textbox(label="5. Final Output")

            with gr.Row():
                snapshot_name = gr.Textbox(
                    label="Snapshot Name",
                    placeholder="Enter a name for this snapshot"
                )
                tags_input = gr.Textbox(
                    label="Tags",
                    placeholder="tag1, tag2, tag3"
                )
                save_btn = gr.Button("💾 Save", variant="secondary")

            with gr.Row():
                snapshot_status = gr.Textbox(label="Status")

        # Saved Snapshots Tab
        with gr.TabItem("Saved Snapshots"):
            with gr.Row():
                search_box = gr.Textbox(
                    label="Search",
                    placeholder="Search snapshots..."
                )
            
            snapshots_table = gr.Dataframe(
                headers=["ID", "Name", "Created At", "Model", "Prompt", "Tags"],
                label="Saved Snapshots",
                value=update_snapshots_table(),
                wrap=True,
                row_count=5
            )
            
            with gr.Row():
                snapshot_id_input = gr.Number(
                    label="Snapshot ID",
                    precision=0,
                    minimum=1,
                    step=1
                )
                
                with gr.Row():
                    load_btn = gr.Button("📂 Load", variant="primary")
                    refresh_btn = gr.Button("🔄 Refresh", variant="secondary")
                    delete_btn = gr.Button("🗑️ Delete", variant="secondary")
                    export_btn = gr.Button("📤 Export", variant="secondary")
            
            # JSON output
            json_output = gr.JSON(
                label="Snapshot Content",
                visible=False  # Initially hidden
            )
            
            operation_status = gr.Textbox(label="Status")

    # Connect components
    submit_btn.click(
        fn=process_question,
        inputs=[
            file_input, user_prompt, system_prompt, 
            cot_prompt, model_selector, use_default_cot
        ],
        outputs=[
            user_prompt_output, initial_response_output, 
            thinking_output, reflection_output, final_output, 
            system_prompt, cot_prompt
        ]
    )
    
    save_btn.click(
        fn=lambda *args: (
            db.save_snapshot({
                'snapshot_name': args[0],
                'user_prompt': args[1],
                'system_prompt': args[2],
                'model_name': args[3],
                'cot_prompt': args[4],
                'initial_response': args[5],
                'thinking': args[6],
                'reflection': args[7],
                'final_response': args[8],
                'tags': args[9]
            }),
            update_snapshots_table()
        ),
        inputs=[
            snapshot_name, user_prompt_output, system_prompt, 
            model_selector, cot_prompt, initial_response_output,
            thinking_output, reflection_output, final_output, 
            tags_input
        ],
        outputs=[snapshot_status, snapshots_table]
    )
    
    delete_btn.click(
        fn=lambda snapshot_id: db.delete_snapshot(int(snapshot_id)) if snapshot_id is not None else ("Please enter a snapshot ID", update_snapshots_table()),
        inputs=[snapshot_id_input],
        outputs=[operation_status, snapshots_table]
    )
    
    refresh_btn.click(
        fn=update_snapshots_table,
        inputs=[search_box],
        outputs=snapshots_table
    )
    
    search_box.change(
        fn=update_snapshots_table,
        inputs=[search_box],
        outputs=snapshots_table
    )
    
    # Update the export button click handler
    def handle_export(snapshot_id):
        """
        Handle the export button click.
        
        Args:
            snapshot_id: ID of the snapshot to export
            
        Returns:
            Tuple of (json_content, status_message)
        """
        if not snapshot_id:
            return gr.update(visible=False, value=None), "Please enter a snapshot ID to export"
        try:
            json_content = export_snapshot(snapshot_id)
            # Try to parse the JSON string to ensure it's valid
            parsed_json = json.loads(json_content)
            return gr.update(visible=True, value=parsed_json), "Export successful"
        except Exception as e:
            return gr.update(visible=False, value=None), f"Export failed: {str(e)}"

    export_btn.click(
        fn=handle_export,
        inputs=[snapshot_id_input],
        outputs=[
            json_output,
            operation_status
        ]
    )

    # Add the load button click event handler
    load_btn.click(
        fn=load_snapshot_by_id,
        inputs=[snapshot_id_input],
        outputs=[
            snapshot_name,
            user_prompt,
            system_prompt,
            model_selector,
            cot_prompt,
            initial_response_output,
            thinking_output,
            reflection_output,
            final_output,
            operation_status
        ]
    )

if __name__ == "__main__":
    iface.launch(share=False)