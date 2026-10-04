-- Top skills inside every role family, ranked with a window function.
WITH role_totals AS (
    SELECT role_family, COUNT(*) AS n_role FROM postings GROUP BY role_family
),
role_skill AS (
    SELECT p.role_family, s.name AS skill, COUNT(*) AS n
    FROM posting_skills ps
    JOIN postings p ON p.posting_id = ps.posting_id
    JOIN skills s ON s.skill_id = ps.skill_id
    GROUP BY p.role_family, s.name
)
SELECT r.role_family, r.skill, r.n, t.n_role, 1.0 * r.n / t.n_role AS share,
       RANK() OVER (PARTITION BY r.role_family ORDER BY r.n DESC) AS rnk
FROM role_skill r
JOIN role_totals t ON t.role_family = r.role_family
WHERE t.n_role >= :min_role_postings
ORDER BY r.role_family, rnk;
