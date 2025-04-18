import os
import subprocess
import json
import re
from typing import TypedDict, Optional, List, Dict
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
load_dotenv()
from langsmith import utils
from langsmith import traceable
from typing import Annotated
import operator
utils.tracing_is_enabled()


# The workflow.py file is used to generate the FAST_API backened project.

model = ChatGroq(model=os.getenv("MODEL"), temperature=0, api_key=os.getenv("GROQ_API_KEY"))



class FileStructureState(TypedDict):
   
   """A TypedDict representing the state of the file structure generation
   process with attributes: srd_text (str), file_structure (Optional[List[str]]),
   file_descriptions (Optional[Dict[str, str]]), folder_path (str), error_log
   Optional[str]), retry_count (int), code_feedback (Optional[Dict[str, str]]),
   improvement_count (int)."""
   
   srd_text: Annotated[str, operator.add] 
   file_structure: Optional[List[str]]
   file_descriptions: Optional[Dict[str, str]]
   folder_path: str
   error_log: Optional[str]
   retry_count: int
   code_feedback: Optional[Dict[str, str]]
   improvement_count: int

from json import JSONDecodeError


@traceable
def srd_to_file_structure(state: FileStructureState) -> FileStructureState:
 
    """Generates a file structure and descriptions from the srd document."""
   
    prompt = f"""
    You are a software architect. Given the following srd document:
    {state["srd_text"]}
    - Generate a structured JSON file tree.
    - Provide a detailed description of each file's purpose and what should be inside it and generate docker file as well and create readme files for every thing and requirements.txt.
    - do not generate tests
    -List all the required file and folder paths.
    -Follow best practices for modern FastAPI projects and better folder structure.
    - Return a JSON object with:
      - 'files': List of file paths.
      - 'descriptions': Dictionary mapping file paths to their descriptions. Each description should comprehensively outline the structure and purpose of the file, including: Classes:List all the classes that should be present in the file., Provide a detailed description of what each class should do.,Explain the role and functionality of each class within the context of the file.,Variables: List all the key variables that should be present in the file., Describe the purpose and usage of each variable., Include details on the scope and type of each variable., Methods: List all the methods that should be present in the file. Provide a detailed description of what each method should do., Explain the inputs, outputs, and side effects of each method.
    - Ensure the response is in valid JSON format without any additional text, markdown, or code blocks.
    """
   
    response = model.invoke(prompt)
    response_str = response.content
    with open("debug_response.json", "w") as debug_file:
        debug_file.write(response_str)
   
    try:
        json_match = re.search(r"```json\s+(.*?)\s+```", response_str, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            json_data = json.loads(json_str)
            try:
                json_data = json.loads(json_str)
            except JSONDecodeError as e:
                print(f"JSONDecodeError: {e}")
                print("Invalid JSON Response:", json_str)
                raise e
            state["file_structure"] = json_data["files"]
            state["file_descriptions"] = json_data["descriptions"]
        else:
            print("JSON data not found in the response.")
    except JSONDecodeError as e:
        print(f"JSONDecodeError: {e}")
        print("Response content is:", response_str)
        raise e
 
    return state

@traceable
def create_files(state: FileStructureState) -> FileStructureState:
 
    """Creates files and stores descriptions for the next step."""
   
    folder_path = state.get("folder_path", "generated_project")
    file_structure = state.get("file_structure", [])
    file_descriptions = state.get("file_descriptions", {})
 
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
 
    for file_path in file_structure:
        full_path = os.path.join(folder_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
 
        with open(full_path, "w") as f:
            f.write(f"# Description: {file_descriptions.get(file_path, 'No description available')}\n\n")
 
    return state

import os
import subprocess
import sys
from dotenv import load_dotenv
 
def write_code_to_files(state: dict) -> dict:
 
    """Writes code into the generated files based on descriptions and
    appends requirements to requirements.txt."""
 
    folder_path = state.get("folder_path", "generated_project")
    file_structure = state.get("file_structure", [])
    file_descriptions = state.get("file_descriptions", {})
 
    requirements = set()
 
    for file_path in file_structure:
        full_path = os.path.join(folder_path, file_path)
        description = file_descriptions.get(file_path, "")
        print(full_path, description)
 
        prompt = f"""
        You are a senior FastAPI developer. Generate a complete Python file based **only** on the following description:  
        {description}  
 
        ### **Constraints:**  
        - **Only generate code for this specific file:** {file_path}  
        - **Do not generate code for any other files.**  
        - **Strictly adhere to the extracted requirements from the description.**  
        - **Do not assume or add extra functionality beyond what is specified.**  
        - **Follow FastAPI best practices, keeping the code minimal yet correct.**  
        - **Use clear and concise variable and function names.**  
        - **Ensure modularity and error handling but avoid unnecessary abstractions.**  
        - **Include only relevant docstrings and comments.**  
        - **Do not generate unit tests unless explicitly requested.**  
        - **Do Not Give Anything Like pip installs and everything that is present should be python. Do not give notes as well.**
        """
 
        response = model.invoke(prompt)
        code = response.content.strip()
 
        code_lines = code.split('\n')
        filtered_code = "\n".join(line for line in code_lines if "```" not in line)
 
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(filtered_code)
 
        for line in code_lines:
            if "import " in line or "from " in line:
                parts = line.split()
                if parts[0] == "import":
                    requirement = parts[1].split('.')[0]
                elif parts[0] == "from":
                    requirement = parts[1].split('.')[0]
                if requirement not in file_structure and requirement != "main" and requirement not in file_descriptions:
                    requirements.add(requirement)
 
    requirements_path = os.path.join(folder_path, "requirements.txt")
    with open(requirements_path, "w") as req_file:
        for requirement in sorted(requirements):
            req_file.write(f"{requirement}\n")
 
    if os.path.exists(requirements_path):
        print("Installing dependencies...")
        try:
            result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements_path], check=True, capture_output=True, text=True)
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Failed to install dependencies: {e}")
 
    venv_path = os.path.join(folder_path, "venv")
    if not os.path.exists(venv_path):
        print("Creating virtual environment...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_path])
 
    if os.name == "nt":
        activate_script = os.path.join(venv_path, "Scripts", "activate")
    else:
        activate_script = os.path.join(venv_path, "bin", "activate")
 
    env_path = os.path.join(folder_path, ".env")
    if not os.path.exists(env_path):
        print("Creating .env file...")
        with open(env_path, "w") as env_file:
            env_file.write("KEY=VALUE\n")  
           
    if os.path.exists(env_path):
        print("Loading environment variables...")
        load_dotenv(env_path)
 
    print("Environment setup complete.")
    return state
 
@traceable
def reflect_on_code(state: FileStructureState) -> FileStructureState:
   
    """Reads the code and provides feedback for improvements."""
 
    print("Reflecting the code")
   
    folder_path = state["folder_path"]
    code_feedback = {}
 
    for file_path in state["file_structure"]:
        full_path = os.path.join(folder_path, file_path)
 
        with open(full_path, "r") as f:
            code = f.read()
 
        prompt = f"""
        You are a senior software reviewer. Analyze the following code:
        ```python
        {code}
        ```
        - Identify any missing logic.
        - Suggest improvements (performance, best practices, security).
        - List the exact modifications required.
        """
 
        response = model.invoke(prompt)
        code_feedback[file_path] = response.content.strip()
 
    state["code_feedback"] = code_feedback
    return state


@traceable
def improve_code(state: FileStructureState) -> FileStructureState:
   
    """Applies improvements based on reflection feedback, with human
    intervention after 3 iterations."""
 
    print("Improving The Code")
   
    folder_path = state["folder_path"]
    code_feedback = state["code_feedback"]
    state["improvement_count"] = state.get("improvement_count",0) + 1
 
   
    for file_path, feedback in code_feedback.items():
        full_path = os.path.join(folder_path, file_path)
 
        with open(full_path, "r") as f:
            existing_code = f.read()
 
        prompt = f"""
        You are a senior software engineer. Improve the following Python code:
        ```python
        {existing_code}
        ```
        Based on the following feedback:
        ```
        {feedback}
        ```
        ### **Constraints:**  
        - **Only generate code for this specific file:** {file_path}  
        - **Do not generate code for any other files.**  
        - **Strictly adhere to the extracted requirements from the description.**  
        - **Do not assume or add extra functionality beyond what is specified.**  
        - **Follow FastAPI best practices, keeping the code minimal yet correct.**  
        - **Use clear and concise variable and function names.**  
        - **Ensure modularity and error handling but avoid unnecessary abstractions.**  
        - **Include only relevant docstrings and comments.**  
        - **Do not generate unit tests unless explicitly requested.**  
        - **Do Not Give Anything Like pip installs and everything that is present should be python. Do not give notes as well.**
        - **Do Not Add Any Thing Likes notes anything extra strict give only the python code**
        -- *** DO NOT MENTION ANYTHING ELSE OTHER THAN PYTHON IN THE FILE I DONT WANT YOUR ASUPTIONS AND EVERY THING ELSE SHOULD NOT BE PRESENT NO EXTRA TEXT SHOULD BE PRESENT***
        """
 
        response = model.invoke(prompt)
        improved_code = response.content.strip()
 
        code_lines = improved_code.split('\n')
        filtered_code = "\n".join(line for line in code_lines if "```" not in line)
 
 
        with open(full_path, "w") as f:
            f.write(filtered_code)
 
    return state


@traceable
def generate_tests(state: FileStructureState) -> FileStructureState:
 
    """
    Reads each Python file present in the generated project folder and generates a test case
    for it based on its content where the tests are stored in "tests" subfolder as separate files.
    """
 
    print("Generating test cases for each Python file...")
    folder_path = state["folder_path"]
    test_folder = os.path.join(folder_path, "tests")
    if not os.path.exists(test_folder):
        os.makedirs(test_folder)
 
    for file_path in state.get("file_structure", []):
        if not file_path.endswith(".py"):
            continue
        full_file_path = os.path.join(folder_path, file_path)
        with open(full_file_path, "r") as f:
            code = f.read()
        print("Creating Test Case For ", full_file_path)
 
        prompt = f"""
        You are a senior software tester.
        Analyze the following Python module:
        ```python
        {code}
        ```
        Based on the module's functionality, generate a complete test case file using a Python testing framework (unittest or pytest).
        Ensure the tests cover core functionality, error handling, and potential edge cases.
         **Constraints:**  
        - **Only generate code for this specific file:**
        - **Do not generate code for any other files.**  
        - **Do not assume or add extra functionality beyond what is specified.**  
        - **Use clear and concise variable and function names.**  
        - **Ensure modularity and error handling but avoid unnecessary abstractions.**  
        - **Include only relevant docstrings and comments.**  
        - **Do Not Give Anything Like pip installs and everything that is present should be python. Do not give notes as well.**
        - **Do Not Add Any Thing Likes notes anything extra strict give only the python code**
        -- *** DO NOT MENTION ANYTHING ELSE OTHER THAN PYTHON IN THE FILE I DONT WANT YOUR ASUPTIONS AND EVERY THING ELSE SHOULD NOT BE PRESENT NO EXTRA TEXT SHOULD BE PRESENT***
        """
        response = model.invoke(prompt)
        test_code = response.content.strip()
 
        test_code = "\n".join(line for line in test_code.splitlines() if "```" not in line)
 
        test_file_name = "test_" + os.path.basename(file_path)
        test_full_path = os.path.join(test_folder, test_file_name)
        with open(test_full_path, "w") as test_file:
            test_file.write(test_code)
        print(f"Generated test case for {file_path} -> {test_file_name}")
 
    return state

@traceable
def run_code(state: FileStructureState) -> FileStructureState:
   
    """Runs the generated code, captures errors, and retries if necessary."""
 
    print("Came Inside Runners")
   
    folder_path = state["folder_path"]
    error_log = None
 
    for file_path in state["file_structure"]:
        full_path = os.path.join(folder_path, file_path)
        if not file_path.endswith(".py"):
            continue
 
        try:
            result = subprocess.run(["python", full_path], capture_output=True, text=True)
            if result.returncode != 0:
                error_log = result.stderr.strip()
                print(f"Error in {file_path}:\n{error_log}")
        except Exception as e:
            error_log = str(e)
 
    state["error_log"] = error_log
    state["retry_count"] += 1
 
    if error_log and state["retry_count"] < MAX_RETRIES:
        return state  # Refining the code and fixing the errors
 
    return state

@traceable
def refine_errors(state: FileStructureState) -> FileStructureState:
 
    """Reflects on errors found during code execution,
    provides suggestions for improvements, and updates the state with feedback."""
   
    if not state["error_log"]:
        print("No errors found, proceeding to final execution.")
        return state  
 
    print("Reflecting on errors...")
    error_summary = "\n".join([f"{k}: {v}" for k, v in state["error_log"].items()])
   
    prompt = f"""
    You are an AI software engineer. The following code execution resulted in errors:
 
    **Error Summary:**
    {error_summary}
 
    Please provide the best suggestions to improve the code and resolve these errors.
    """
 
    response = model.invoke(prompt)
    code_feedback[file_path] = response.content.strip()
 
    state["code_feedback"] = code_feedback
   
    return state


@traceable
def final_execution(state: FileStructureState) -> FileStructureState:
 
    """Runs the final version of the error-free code."""
   
    folder_path = state["folder_path"]
 
    for file_path in state["file_structure"]:
        full_path = os.path.join(folder_path, file_path)
        if not file_path.endswith(".py"):
            continue  # Skip non-Python files
 
        print(f"Running final version: {file_path}")
        subprocess.run(["python", full_path])
 
    return state

import shutil
from pathlib import Path
@traceable
def zip_project_folder(folder_path: str) -> str:
    """
    Compress the entire folder into a zip file.

    Args:
        folder_path (str): Path to the folder to be zipped.

    Returns:
        str: Path to the created zip file.
    """
    folder = Path(folder_path)
    zip_path = folder.with_suffix(".zip")  # e.g., "generated_project.zip"

    print(f"Zipping folder: {folder} -> {zip_path}")
    shutil.make_archive(base_name=str(folder), format="zip", root_dir=folder)

    return str(zip_path)

graph = StateGraph(FileStructureState)
for fn in [srd_to_file_structure, create_files, write_code_to_files, reflect_on_code,
           improve_code, generate_tests, run_code, refine_errors, final_execution]:
    graph.add_node(fn.__name__, fn)

edges = [
    (START, 'srd_to_file_structure'),
    ('srd_to_file_structure', 'create_files'),
    ('create_files', 'write_code_to_files'),
    ('write_code_to_files', 'reflect_on_code'),
    ('reflect_on_code', 'improve_code'),
    ('improve_code', 'generate_tests'),
    ('generate_tests', 'run_code'),
    ('run_code', 'refine_errors'),
    ('refine_errors', 'improve_code'),
    ('run_code', 'final_execution'),
    ('final_execution', END)
]
for src, dst in edges:
    graph.add_edge(src, dst)

workflow=graph.compile()

def read_extracted_text():
    with open("extracted_text.txt", "r") as f:
        return f.read()
srd_text_doc = read_extracted_text()

initial_state = {
    "srd_text": srd_text_doc,
    "file_structure": None,
    "file_descriptions": None,
    "folder_path": "generated_project",
    "error_log": None,
    "retry_count": 0,
    "code_feedback": None
}

workflow.invoke(initial_state)