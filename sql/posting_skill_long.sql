-- One row per (posting, skill): the base table for the pandas analyses.
SELECT p.posting_id, p.role_family, p.seniority, p.city, p.salary_lpa, p.first_seen_week, s.name AS skill
FROM posting_skills ps
JOIN postings p ON p.posting_id = ps.posting_id
JOIN skills s ON s.skill_id = ps.skill_id;
