-- Project Evolve runtime schema additions.
-- Main tables such as faculty, student_feedback, peer_reviews,
-- performance_metrics, course_materials, and evaluation_results are created
-- by 01_Data_Layer_Phase1.ipynb and 2_AI_Layer_Phase.ipynb.

CREATE TABLE IF NOT EXISTS faculty_feedback (
    id SERIAL PRIMARY KEY,
    faculty_id INTEGER,
    understandability_score INTEGER CHECK (understandability_score BETWEEN 1 AND 5),
    trust_score INTEGER CHECK (trust_score BETWEEN 1 AND 5),
    comment TEXT,
    xai_viewed BOOLEAN DEFAULT FALSE,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shap_explanations (
    faculty_id INTEGER PRIMARY KEY,
    shap_values_json TEXT,
    base_value FLOAT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blockchain_audit_logs (
    id SERIAL PRIMARY KEY,
    evaluation_id INTEGER,
    faculty_id INTEGER NOT NULL,
    result_hash TEXT NOT NULL,
    blockchain_tx_hash TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'logged'
);
