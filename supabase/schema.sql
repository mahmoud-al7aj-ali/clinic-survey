-- Run once in Supabase → SQL Editor

CREATE TABLE IF NOT EXISTS surveys (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    brand_name TEXT NOT NULL DEFAULT 'نظام إدارة العيادات الذكي',
    tag TEXT DEFAULT 'استطلاع أولويات',
    intro_text TEXT,
    promo_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    promo_badge TEXT DEFAULT 'خصم 10%',
    promo_text TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sections (
    id BIGSERIAL PRIMARY KEY,
    survey_id BIGINT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    page_order INTEGER NOT NULL DEFAULT 0,
    page_label TEXT,
    page_title TEXT,
    page_num TEXT,
    UNIQUE (survey_id, page_order)
);

CREATE TABLE IF NOT EXISTS feature_groups (
    id BIGSERIAL PRIMARY KEY,
    section_id BIGINT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    icon TEXT DEFAULT '📋',
    title TEXT NOT NULL,
    subtitle TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS features (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES feature_groups(id) ON DELETE CASCADE,
    feature_num INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    long_description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    question_type TEXT NOT NULL DEFAULT 'rating'
);

CREATE TABLE IF NOT EXISTS responses (
    id BIGSERIAL PRIMARY KEY,
    survey_id BIGINT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    doctor_name TEXT NOT NULL,
    clinic_name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    notes TEXT,
    wants_updates BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS response_answers (
    id BIGSERIAL PRIMARY KEY,
    response_id BIGINT NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    feature_id BIGINT NOT NULL REFERENCES features(id),
    rating TEXT NOT NULL,
    UNIQUE (response_id, feature_id)
);

CREATE TABLE IF NOT EXISTS admin_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

ALTER TABLE surveys DISABLE ROW LEVEL SECURITY;
ALTER TABLE sections DISABLE ROW LEVEL SECURITY;
ALTER TABLE feature_groups DISABLE ROW LEVEL SECURITY;
ALTER TABLE features DISABLE ROW LEVEL SECURITY;
ALTER TABLE responses DISABLE ROW LEVEL SECURITY;
ALTER TABLE response_answers DISABLE ROW LEVEL SECURITY;
ALTER TABLE admin_users DISABLE ROW LEVEL SECURITY;
