DROP TABLE IF EXISTS attempt_activity_logs CASCADE;
DROP TABLE IF EXISTS question_rubrics CASCADE;
DROP TABLE IF EXISTS quiz_section_questions CASCADE;
DROP TABLE IF EXISTS quiz_sections CASCADE;
DROP TABLE IF EXISTS student_accommodations CASCADE;
DROP TABLE IF EXISTS question_bank_item_versions CASCADE;
DROP TABLE IF EXISTS question_bank_items CASCADE;
DROP TABLE IF EXISTS question_banks CASCADE;
DROP TABLE IF EXISTS quiz_question_versions CASCADE;
DROP TABLE IF EXISTS quiz_groups CASCADE;
DROP TABLE IF EXISTS attempt_answers CASCADE;
DROP TABLE IF EXISTS exam_attempts CASCADE;
DROP TABLE IF EXISTS question_options CASCADE;
DROP TABLE IF EXISTS quiz_questions CASCADE;
DROP TABLE IF EXISTS group_members CASCADE;
DROP TABLE IF EXISTS exam_sessions CASCADE;
DROP TABLE IF EXISTS quizzes CASCADE;
DROP TABLE IF EXISTS user_groups CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS extended_users CASCADE;
DROP TABLE IF EXISTS institutes CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('administrator', 'teacher', 'student')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_users_username_lower ON users (lower(username));
CREATE UNIQUE INDEX idx_users_email_lower ON users (lower(email));

CREATE TABLE institutes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institute_name VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE extended_users (
    id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    acc_name VARCHAR(255) NOT NULL,
    institute_id UUID NOT NULL REFERENCES institutes(id),
    institute_member_number VARCHAR(64),
    phone VARCHAR(30),
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    email_verified_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (institute_id, institute_member_number)
);

CREATE INDEX idx_extended_users_institute_id ON extended_users(institute_id);

CREATE TABLE user_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_name VARCHAR(255) NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    creating_teacher UUID NOT NULL REFERENCES users(id),
    institute_id UUID NOT NULL REFERENCES institutes(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_groups_institute_id ON user_groups(institute_id);
CREATE INDEX idx_user_groups_creating_teacher ON user_groups(creating_teacher);

CREATE TABLE group_members (
    group_id UUID NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (group_id, user_id)
);

CREATE INDEX idx_group_members_user_id ON group_members(user_id);

CREATE TABLE quizzes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id UUID NOT NULL REFERENCES users(id),
    title VARCHAR(200) NOT NULL,
    duration_minutes INT NOT NULL CHECK (duration_minutes > 0),
    instructions TEXT,
    shuffle_questions BOOLEAN NOT NULL DEFAULT FALSE,
    shuffle_options BOOLEAN NOT NULL DEFAULT FALSE,
    questions_to_serve INT CHECK (questions_to_serve > 0),
    allow_multiple_attempts BOOLEAN NOT NULL DEFAULT FALSE,
    scoring_policy VARCHAR(10) NOT NULL DEFAULT 'latest'
        CHECK (scoring_policy IN ('latest', 'best', 'average')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_quizzes_teacher_id ON quizzes(teacher_id);

CREATE TABLE quiz_groups (
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
    PRIMARY KEY (quiz_id, group_id)
);

CREATE INDEX idx_quiz_groups_group_id ON quiz_groups(group_id);

CREATE TABLE exam_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    join_code VARCHAR(10) UNIQUE NOT NULL CHECK (join_code = upper(join_code)),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    max_attempts INT NOT NULL DEFAULT 1 CHECK (max_attempts > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_time > start_time)
);

CREATE INDEX idx_exam_sessions_quiz_id ON exam_sessions(quiz_id);

CREATE TABLE quiz_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type VARCHAR(30) NOT NULL CHECK (
        question_type IN (
            'single_choice', 'multiple_choice', 'true_false', 'short_answer',
            'numeric', 'fill_blank', 'matching', 'ordering', 'hotspot',
            'drag_drop', 'code', 'long_answer'
        )
    ),
    points INT NOT NULL DEFAULT 1 CHECK (points > 0),
    position INT NOT NULL DEFAULT 0 CHECK (position >= 0),
    image_url TEXT,
    accepted_answers JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    interaction_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    media JSONB NOT NULL DEFAULT '[]'::jsonb,
    parameter_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    feedback TEXT,
    worked_solution TEXT,
    partial_credit JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    difficulty SMALLINT CHECK (difficulty BETWEEN 1 AND 5),
    standard_code VARCHAR(128),
    blooms_level VARCHAR(16) CHECK (
        blooms_level IN ('remember', 'understand', 'apply', 'analyze', 'evaluate', 'create')
    ),
    folder_path VARCHAR(500),
    version INT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_quiz_questions_quiz_position
    ON quiz_questions(quiz_id, position, created_at);

CREATE TABLE quiz_question_versions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    version INT NOT NULL,
    question JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (question_id, version)
);

CREATE TABLE question_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    option_text TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    position INT NOT NULL DEFAULT 0 CHECK (position >= 0),
    media JSONB NOT NULL DEFAULT '[]'::jsonb,
    feedback TEXT
);

CREATE INDEX idx_question_options_question_position
    ON question_options(question_id, position);

CREATE TABLE exam_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deadline_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'submitted')),
    question_snapshot JSONB NOT NULL,
    accommodation_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    log_text TEXT,
    score DOUBLE PRECISION,
    max_score DOUBLE PRECISION,
    graded_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempt_number INT NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
    UNIQUE (exam_session_id, student_id, attempt_number)
);

CREATE INDEX idx_exam_attempts_student_id ON exam_attempts(student_id);

CREATE TABLE attempt_answers (
    attempt_id UUID NOT NULL REFERENCES exam_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL,
    selected_option_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    text_answer TEXT,
    answer_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    points_awarded DOUBLE PRECISION,
    grader_feedback TEXT,
    graded_by UUID REFERENCES users(id),
    graded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (attempt_id, question_id)
);

CREATE TABLE question_banks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    institute_id UUID REFERENCES institutes(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_question_banks_owner ON question_banks(owner_id);
CREATE INDEX idx_question_banks_institute ON question_banks(institute_id);

CREATE TABLE question_bank_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_id UUID NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
    question JSONB NOT NULL,
    version INT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_question_bank_items_bank ON question_bank_items(bank_id, updated_at DESC);
CREATE INDEX idx_question_bank_items_tags
    ON question_bank_items USING GIN ((question->'tags'));

CREATE TABLE question_bank_item_versions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id UUID NOT NULL REFERENCES question_bank_items(id) ON DELETE CASCADE,
    version INT NOT NULL,
    question JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_id, version)
);

CREATE TABLE quiz_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    position INT NOT NULL DEFAULT 0 CHECK (position >= 0),
    instructions TEXT,
    time_limit_minutes INT CHECK (time_limit_minutes > 0),
    shuffle_questions BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (quiz_id, position)
);

CREATE TABLE quiz_section_questions (
    section_id UUID NOT NULL REFERENCES quiz_sections(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    position INT NOT NULL DEFAULT 0 CHECK (position >= 0),
    depends_on_question_id UUID REFERENCES quiz_questions(id) ON DELETE SET NULL,
    dependency_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (section_id, question_id)
);

CREATE TABLE student_accommodations (
    student_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    extra_time_percent INT NOT NULL DEFAULT 0 CHECK (extra_time_percent BETWEEN 0 AND 200),
    read_aloud BOOLEAN NOT NULL DEFAULT FALSE,
    large_text BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by UUID NOT NULL REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (student_id, quiz_id)
);

CREATE TABLE attempt_activity_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attempt_id UUID NOT NULL REFERENCES exam_attempts(id) ON DELETE CASCADE,
    event_type VARCHAR(32) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_attempt_activity_attempt ON attempt_activity_logs(attempt_id, created_at);

CREATE TABLE question_rubrics (
    question_id UUID NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    position INT NOT NULL CHECK (position >= 0),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    max_points DOUBLE PRECISION NOT NULL CHECK (max_points > 0),
    PRIMARY KEY (question_id, position)
);

CREATE TABLE sessions (
    token_hash CHAR(64) PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);