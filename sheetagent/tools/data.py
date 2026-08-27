"""Name/department pools for realistic sample data."""
FIRST_NAMES = [
    "John", "Alice", "Priya", "Marcus", "Sofia", "Daniel", "Aisha", "Liam",
    "Mei", "Carlos", "Hannah", "Omar", "Elena", "Jacob", "Nia", "Ravi",
    "Grace", "Tomas", "Yuki", "Isabel", "Noah", "Fatima", "Ethan", "Chloe",
    "Arjun", "Maya", "Victor", "Leila", "Samuel", "Ines",
]
LAST_NAMES = [
    "Smith", "Brown", "Sharma", "Okafor", "Rossi", "Kim", "Hassan", "Walsh",
    "Chen", "Alvarez", "Novak", "Farouk", "Petrova", "Miller", "Adeyemi",
    "Iyer", "Bennett", "Silva", "Tanaka", "Moreno", "Clarke", "Rahman",
    "Fischer", "Dubois", "Nair", "Lindqvist", "Popescu", "Haddad",
]
DEPARTMENTS = {
    # department -> (titles, salary band)
    "Engineering": (["Software Engineer", "Senior Engineer", "QA Engineer",
                     "DevOps Engineer", "Engineering Manager"], (78000, 165000)),
    "Sales":       (["Account Executive", "Sales Development Rep",
                     "Regional Sales Manager"], (52000, 118000)),
    "Marketing":   (["Content Strategist", "Growth Marketer",
                     "Brand Manager"], (55000, 112000)),
    "HR":          (["HR Generalist", "Recruiter", "People Partner"], (48000, 98000)),
    "Finance":     (["Financial Analyst", "Accountant", "Controller"], (60000, 135000)),
    "Support":     (["Support Specialist", "Support Team Lead"], (42000, 82000)),
    "Operations":  (["Operations Analyst", "Logistics Coordinator"], (46000, 96000)),
}
LOCATIONS = ["New York", "London", "Bengaluru", "Berlin", "Singapore",
             "Toronto", "Sydney", "Austin", "Dublin", "Remote"]
