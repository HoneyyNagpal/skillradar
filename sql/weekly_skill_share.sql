-- Weekly share of postings that mention each skill, on a complete week x skill grid
-- (zero weeks included, so the moving average is not computed over gaps).
-- Window functions: 4-week moving average and week-over-week change per skill.
WITH weeks AS (
    SELECT first_seen_week AS week_start, COUNT(*) AS n_postings
    FROM postings
    GROUP BY first_seen_week
),
grid AS (
    SELECT w.week_start, w.n_postings, s.skill_id, s.name AS skill
    FROM weeks w CROSS JOIN skills s
),
counts AS (
    SELECT p.first_seen_week AS week_start, ps.skill_id, COUNT(*) AS n_mentions
    FROM posting_skills ps
    JOIN postings p ON p.posting_id = ps.posting_id
    GROUP BY p.first_seen_week, ps.skill_id
),
shares AS (
    SELECT g.week_start, g.skill, g.n_postings,
           COALESCE(c.n_mentions, 0) AS n_mentions,
           1.0 * COALESCE(c.n_mentions, 0) / g.n_postings AS share
    FROM grid g
    LEFT JOIN counts c ON c.week_start = g.week_start AND c.skill_id = g.skill_id
)
SELECT week_start, skill, n_postings, n_mentions, share,
       AVG(share) OVER (PARTITION BY skill ORDER BY week_start
                        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)  AS share_ma4,
       share - LAG(share) OVER (PARTITION BY skill ORDER BY week_start) AS wow_change
FROM shares
ORDER BY skill, week_start;
