"""Workflow incident-triage sample app.

M1 step 2b: the agent itself drives workflows through the injected
``start_workflow`` / ``get_workflow_status`` tools. The framework reads
``workflows.enabled: true`` from ``main.agent.md`` and handles all the
wiring — this file just builds the app.
"""

from azure_functions_agents import create_function_app

app = create_function_app()
