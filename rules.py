def recommend_services(industry, company_size, goal):
    if industry.lower() == "publishing":
        return [
            "Copy editing",
            "Proofreading",
            "Content distribution"
        ]

    if goal.lower() == "lead generation":
        return [
            "Website copywriting",
            "Landing page creation",
            "SEO optimization"
        ]

    return [
        "Content strategy",
        "Website content audit"
    ]
