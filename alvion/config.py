"""Paths, defaults and the model registry."""
import json
import os

APP_NAME = "ALVION"
VERSION = "1.0.0"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(BASE_DIR, "alvion")
DATA_DIR = os.environ.get("ALVION_DATA", os.path.join(BASE_DIR, "data"))
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
DB_PATH = os.path.join(DATA_DIR, "alvion.db")
MASTER_KEY_PATH = os.path.join(DATA_DIR, "master.key")
WEB_DIR = os.path.join(PKG_DIR, "web")
KNOWLEDGE_DIR = os.path.join(PKG_DIR, "knowledge")
REGISTRY_PATH = os.path.join(PKG_DIR, "model_registry.json")

for _d in (DATA_DIR, JOBS_DIR):
    os.makedirs(_d, exist_ok=True)

# Claude. Opus 5 is the default; changeable per user in Settings.
DEFAULT_PLANNER_MODEL = "claude-opus-5"
PLANNER_EFFORT = "high"

HIGGSFIELD_BASE = "https://api.higgsfield.ai"

SESSION_COOKIE = "alvion_session"
SESSION_DAYS = 30

# Job state machine.
STATES_OLD = [
    "draft", "planning", "awaiting_approval", "generating_frames",
    "generating_clips", "assembling", "completed", "failed", "canceled",
]
# The human-in-the-loop pipeline. Every *_review state waits for the user.
STATES = [
    "draft", "planning", "plan_review",
    "generating_images", "images_review",
    "generating_clips", "clips_review",
    "edit_setup", "rendering", "completed",
    "failed", "canceled",
]
REVIEW_STATES = {"plan_review", "images_review", "clips_review", "edit_setup", "completed"}
TERMINAL_STATES = {"completed", "failed", "canceled"}


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def job_dir(job_id):
    d = os.path.join(JOBS_DIR, job_id)
    for sub in ("frames", "clips", "cut", "final", "inputs"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d
