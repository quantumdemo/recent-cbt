# UCH Staff Secondary School CBT Platform

This is a lightweight yet large-scale Computer-Based Test (CBT) platform developed for UCH Staff Secondary School.

## Features

*   **Modern Landing Page**: A responsive and professional landing page with a clean, academic aesthetic.
*   **User Roles**: Separate interfaces and functionality for Students, Teachers, and Admins.
*   **Exam Management**: Teachers can create exams, add questions manually or via file upload, and view analytics.
*   **Student Interface**: Students can view available exams, take them with a timed interface, and view their results.
*   **Admin Panel**: Admins can approve teacher signups and manage all users.

## Technical Stack

*   **Backend**: Python (Flask)
*   **Database**: PostgreSQL
*   **Frontend**: HTML, CSS, JavaScript

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd cbt_platform
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Set up the database:**
    *   Make sure you have PostgreSQL installed and running.
    *   Create a new database for the project.
    *   Create a `.env` file in the `cbt_platform` directory and add your database URL:
        ```
        DATABASE_URL="postgresql://user:password@localhost/your_db_name"
        SECRET_KEY="a-very-secret-key"
        # Add mail server credentials for notifications
        MAIL_SERVER="smtp.gmail.com"
        MAIL_PORT=587
        MAIL_USE_TLS=True
        MAIL_USERNAME="your-email@gmail.com"
        MAIL_PASSWORD="your-password"
        ```

4.  **Initialize the database:**
    ```bash
    cd app
    flask initdb
    ```

## Running the Application

From the `cbt_platform/app` directory, run:
```bash
flask run
```

The application will be available at `http://127.0.0.1:5000`.

## Admin Creation

To create an admin user, run the following command from the `cbt_platform/app` directory:
```bash
flask create-admin "Admin Name" "admin@example.com" "password"
```

You can then log in as the admin at `/admin/login`.

## Question Upload Format

You can upload questions in bulk using a CSV or Excel file. The file must have the following columns:

*   `question_text`: The text of the question.
*   `question_type`: Must be one of `single-choice`, `multiple-choice`, or `short-answer`.
*   `option1`, `option2`, `option3`, `option4`: The options for single-choice or multiple-choice questions.
*   `correct_answer`:
    *   For `single-choice`, this should be the number of the correct option (e.g., `1` for `option1`).
    *   For `multiple-choice`, this should be a comma-separated list of the correct option numbers (e.g., `1,3`).
    *   For `short-answer`, this should be the exact correct answer.

Sample `sample_questions.csv` and `sample_questions.xlsx` files are provided in the `cbt_platform` directory.
