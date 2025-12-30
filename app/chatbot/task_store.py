"""
Task storage module for background tasks.

This module provides functions for storing and retrieving background tasks.
"""

import os
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store background tasks
background_tasks = {}

# Path to the file where background tasks will be persisted
TASKS_FILE_PATH = os.path.join(os.getcwd(), "uploads", "knowledge_base", "tasks.json")

# Create directory if it doesn't exist
os.makedirs(os.path.dirname(TASKS_FILE_PATH), exist_ok=True)

# Load background tasks from file if it exists
def load_background_tasks():
    global background_tasks
    try:
        if os.path.exists(TASKS_FILE_PATH):
            with open(TASKS_FILE_PATH, 'r') as f:
                background_tasks = json.load(f)
                logger.info(f"Loaded {len(background_tasks)} background tasks from file")
    except Exception as e:
        logger.error(f"Error loading background tasks from file: {e}")
        background_tasks = {}

# Save background tasks to file
def save_background_tasks():
    try:
        with open(TASKS_FILE_PATH, 'w') as f:
            json.dump(background_tasks, f)
            logger.info(f"Saved {len(background_tasks)} background tasks to file")
    except Exception as e:
        logger.error(f"Error saving background tasks to file: {e}")

# Load background tasks on module import
load_background_tasks()