SELECT d.dept_name, COUNT(*) AS num_students
FROM students s
JOIN departments d ON s.dept_id = d.dept_id
JOIN enrollments e ON s.sid = e.sid
JOIN courses c ON e.cid = c.cid
WHERE d.dept_name = 'CS'
  AND c.title LIKE '%Database%'
GROUP BY d.dept_name
HAVING COUNT(*) >= 2;
