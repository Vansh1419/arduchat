# Arduchat

## Overview
Arduchat is a web application that uses custom crawlers to extract telemetry data from ArduPilot drones, processes that data through a machine learning model, and displays the results in real-time. 

It is built with a **FastAPI** backend and a **Streamlit** frontend.

---

## Project Structure
```text
arduchat/
└── src/
    ├── backend.py          # FastAPI server & ML model code
    ├── frontend.py         # Streamlit user interface
    └── requirements.txt    # Python dependencies

```

---

## How to Setup and Run

### 1. Clone & Navigate

```bash
git clone https://github.com/Vansh1419/arduchat
cd arduchat

```

### 2. Install Dependencies

Create a virtual environment and install the required packages using `uv`:

```bash
uv venv --python=3.12
source .venv/bin/activate      # On Windows use: .venv\Scripts\activate
uv pip install -r src/requirements.txt

```

### 3. Start the Application

Run both the backend and frontend simultaneously with a single command from the project root:

```bash
cd src && uvicorn backend:app --reload & streamlit run frontend.py

```

* **Frontend UI:** Access the dashboard at `http://localhost:8501`
* **API Documentation:** View the interactive API docs at `http://localhost:8000/docs`



- Remember to add your own .env file. Please refer to the `.env.example` file for guidance on the required environment variables.