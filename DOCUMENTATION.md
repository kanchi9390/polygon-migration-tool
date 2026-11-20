# How the tool works

A new person can follow one click from the page to the database or to Polygon.

## 1. Login

1. Open `/users/login/` and enter email and password then click Login.
2. The form sends `email` and `password`.
3. `login_view` in `users/views.py` checks `authenticate` of user creds. `EmailBackend` in `users/backends.py` checks the user by email and checks the password. If `is_staff` is true, the user is logged in.
4. Login not required polygon or storage.
5. Django stores the login session of user.
6. User faces the problem page. If the user is not staff, the page shows "You do not have staff access." If user enters wrong password shows "Invalid email or password."

## 2. Fetch a problem

1. Type the Polygon id and click Fetch Problem.
2. The form sends `problem_id`.
3. `index` in `problems/views.py` downloads the package, reads `problem.html`, then calls `get_all_test_cases` in `polygon_api.py`. That function asks for every test, one input and one output at a time. The testcases are saved in Redis for 30 minutes. A normal fetch does not read Redis first.
4. Polygon calls: `problem.tests`, `problem.testInput`, `problem.testAnswer`.
5. Redis updated with testcases But problem table is not  updated yet.
6. The page shows the statement and the test list. "Migrate Test Cases to Storage" and "Migrate Test Description to Database" stay disabled until the problem is saved in the database.

## 3. Create/Update problem in Database

1. Select a difficulty, add tags, and click "Create/Update problem in Database."
2. The form sends `problem_id`, `migrate_to_db`, `difficulty`, and `tags`.
3. `index` checks whether user selects difficulty. If a row exists Polygon id already, it updates the row. If not, it creates new row. The slug is taken from the title. Sample tests are taken from Redis, or from Polygon if Redis is empty.
4. Polygon is called only when the testcases are not in Redis.
5. Testcases are written in `problems_problem`. Tags added to `problems_problemtag`. Sample tests go to `problems_sampletestcase`.
6. The page shows the problem was created or updated. If the same slug already exists in database, the banner displays the raw errorr like `DETAIL: Key (slug)=(sum-of-two-numbers) already exists` .

## 4. Migrate Test Description to Database

1. Click "Migrate Test Description to Database." This button works only after the problem is in the database.
2. The form sends `problem_id` and `migrate_test_cases_to_db`.
3. `index` loads testcases from Redis. For each testcase it keeps only the first 260 characters of input and output, then updates or inserts a row. It does not delete old rows that Polygon no longer has.
4. Polygon is called only when Redis doesn't have test cases of this problem.
5. Testacses are written in `problems_problemtestcase`.
6. The banner shows "Test cases description migrated to database Successfully."

## 5. Migrate Test Cases to Storage

1. Click "Migrate Test Cases to Storage." This botton also waits until the problem is in the database.
2. The form sends `problem_id` and `migrate_to_storage`.
3. `migrate_to_storage` in `polygon_api.py` finds out the database id, deletes the old files of that id, and uploads the full input and output. `get_storage()` in `problems/storage.py` . I have used MinIO for storage.
4. MinIO is called for storing testcases in the storage.
5. Files are stored testcases under `test_cases/{database id}/`. The input file is `01`. The output file is `01.a`. The full text is kept. It is not cut to 260 characters.
6. The banner displays the test cases were migrated to storage.

## Polygon and storage

- Each polygon fetch call goes to `https://polygon.codeforces.com/api/`.
- `_generate_api_sig` in `polygon_api.py` adds the API key and the time, The secrets are stored in `.env`.
- The calls used here to fetch & store the problem `problem.info`, `problem.packages`, `problem.package`, `problem.tests`, `problem.testInput`, `problem.testAnswer`, `problem.checker`, `problem.solutions`, and `problem.viewSolution`.
- The Storage files stored in `test_cases/{database_id}/`. Input is `01`. Output is `01.a`. Test 15 is `15` and `15.a`.
