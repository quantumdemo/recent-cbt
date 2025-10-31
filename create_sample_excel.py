import pandas as pd

data = {'question_text': ["What is the capital of France?", "Which of the following are primary colors?", "What is 2 + 2?"],
        'question_type': ['single-choice', 'multiple-choice', 'short-answer'],
        'option1': ['Paris', 'Red', ''],
        'option2': ['London', 'Green', ''],
        'option3': ['Berlin', 'Blue', ''],
        'option4': ['Rome', 'Yellow', ''],
        'correct_answer': ['1', '1,3', '4']}

df = pd.DataFrame(data)
df.to_excel('cbt_platform/sample_questions.xlsx', index=False)



import pandas as pd

# Create a DataFrame with sample user data
data = {
    'fullname': ['John Doe', 'Jane Smith', 'Peter Jones', 'Mary Williams'],
    'email': ['john.doe@example.com', 'jane.smith@example.com', 'peter.jones@example.com', 'mary.w@example.com'],
    'password': ['password123', 'password456', 'securepass', 'teacherpass'],
    'role': ['student', 'student', 'teacher', 'teacher'],
    'gender': ['Male', 'Female', 'Male', 'Female'],
    'class': ['JSS 1', 'JSS 2', '', '']
}
df = pd.DataFrame(data)

# Create an Excel writer and save the DataFrame to an .xlsx file
try:
    writer = pd.ExcelWriter('sample_users.xlsx', engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Users')
    writer.close()
    print("Successfully created sample_users.xlsx")
except Exception as e:
    print(f"Error creating Excel file: {e}")