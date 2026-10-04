-- How many postings mention both skills of every pair (a.skill_id < b.skill_id avoids mirrored duplicates).
SELECT a.skill_id AS skill_a, b.skill_id AS skill_b, COUNT(*) AS n_both
FROM posting_skills a
JOIN posting_skills b ON a.posting_id = b.posting_id AND a.skill_id < b.skill_id
GROUP BY a.skill_id, b.skill_id
HAVING COUNT(*) >= :min_support;
