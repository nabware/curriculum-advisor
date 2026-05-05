#!/usr/bin/env python3
"""
Generate synthetic professor reviews for development and testing.

This script creates realistic, diverse reviews for all professors in the database.
Each professor gets 3-5 reviews covering different aspects (teaching style, difficulty,
grading, communication, course design) with varied sentiment (positive, neutral, negative).

Usage:
    python scripts/generate_synthetic_reviews.py [--output-csv OUTPUT_PATH] [--reviews-per-professor N]
    
Examples:
    python scripts/generate_synthetic_reviews.py
    python scripts/generate_synthetic_reviews.py --output-csv data/seed/professor_review_snippets.csv --reviews-per-professor 5
"""

import argparse
import csv
import random
import sqlite3
from pathlib import Path
from typing import Optional

# Review templates organized by sentiment and topic
REVIEW_TEMPLATES = {
    "positive": {
        "teaching_style": [
            "Excellent lecturer. Very knowledgeable and engaging. Made complex concepts easy to understand.",
            "Amazing professor! Explains concepts clearly and is always available for questions.",
            "One of the best teachers I've had. Passionate about the subject and it shows.",
            "Clear explanations and great use of examples. Really helped me understand the material.",
            "Engaging lectures. Professor makes the subject interesting and accessible.",
            "Great at breaking down complex topics. Delivers content in an understandable way.",
            "Fantastic instructor. Brings enthusiasm to every class.",
        ],
        "difficulty": [
            "Challenging but fair. The material is difficult but the professor makes it manageable.",
            "Rigorous course but teaches you valuable skills. Worth the effort.",
            "Hard class but you learn a lot. The difficulty is appropriate for the subject.",
            "Takes time to understand but totally worth it. Built strong foundations.",
        ],
        "grading": [
            "Fair grader. Clear rubrics and rubrics are well-explained. Grades are consistent.",
            "Transparent grading. Always explains why you got the grade you did.",
            "Generous with partial credit. Appreciates effort and understanding.",
            "Grades fairly based on the rubric provided at the beginning.",
        ],
        "communication": [
            "Very responsive to emails and questions. Approachable and helpful.",
            "Great office hours. Always willing to help and explain concepts further.",
            "Communicates expectations clearly. Always available when you need help.",
            "Open to feedback and adjusts the course based on student needs.",
        ],
        "course_design": [
            "Excellent course design. Assignments are well-structured and build on each other.",
            "Well-organized course. Topics flow logically and prerequisites are clear.",
            "Great project-based learning approach. Practical and engaging.",
            "Materials are well-organized. Clear syllabus and expectations from day one.",
        ],
    },
    "neutral": {
        "teaching_style": [
            "Decent lecturer. Covers the material but sometimes lacks enthusiasm.",
            "Okay professor. Explains concepts but could be more engaging.",
            "Standard teaching approach. Gets the job done but nothing special.",
            "Delivers content as expected. Not the most engaging but competent.",
            "Straightforward instructor. Teaches what's in the syllabus.",
        ],
        "difficulty": [
            "Course is as difficult as expected for the subject. Fair amount of work.",
            "Standard difficulty level. Not easy but not unreasonably hard.",
            "Medium difficulty. Course content is comprehensive but manageable.",
            "Moderate workload. Amount of material is typical for this type of course.",
        ],
        "grading": [
            "Standard grading. Tests and assignments are graded fairly based on rubrics.",
            "Grading is straightforward. If you do the work, you get a decent grade.",
            "Fair grader. Grades based on the rubric provided in the syllabus.",
            "Grading is what you'd expect. Clear standards and consistent application.",
        ],
        "communication": [
            "Available during office hours. Responds to emails within a few days.",
            "Communicates clearly about expectations. Feedback is provided regularly.",
            "Gets the job done with communication. Responsive but not overly available.",
            "Office hours are available if needed. Responds to student questions.",
        ],
        "course_design": [
            "Course is organized logically. Topics connect to each other.",
            "Well-structured course. You know what to expect and when.",
            "Course design is solid. Assignments connect to lecture material.",
            "Organized course. Clear structure and reasonable progression of topics.",
        ],
    },
    "negative": {
        "teaching_style": [
            "Lectures are hard to follow. Goes too fast without adequate explanation.",
            "Not the clearest instructor. Could explain concepts better before diving deep.",
            "Disorganized class structure. Lectures jump around and lack coherence.",
            "Difficult to understand explanations. Could benefit from clearer delivery.",
            "Boring lectures. Lacks enthusiasm and makes the material feel dry.",
        ],
        "difficulty": [
            "Way too much material for the time available. Pacing is rushed.",
            "Unreasonably difficult for an introductory course. Felt overwhelmed.",
            "Course was overwhelming. Too many concepts crammed together.",
            "Difficulty level was higher than expected. Not enough support provided.",
            "Too much content, not enough time to absorb it properly.",
        ],
        "grading": [
            "Harsh grader. Grades don't reflect effort put in.",
            "Strict rubrics with little room for partial credit. Unforgiving grading.",
            "Grades seem arbitrary. Hard to predict what will get full credit.",
            "Difficulty grader. Even correct work sometimes gets marked down.",
        ],
        "communication": [
            "Hard to get help. Office hours are limited and email responses are slow.",
            "Doesn't explain reasoning for grades. Feedback is minimal.",
            "Difficult to reach. Seems unavailable when you need help.",
            "Poor communication about expectations. Lots of ambiguity.",
        ],
        "course_design": [
            "Course organization is confusing. Topics don't flow logically.",
            "Disorganized course. Syllabus doesn't match what actually happens.",
            "Course is poorly structured. Assignments don't align with lectures.",
            "Bad course design. Prerequisites not clearly indicated.",
        ],
    },
}

CLOSING_STATEMENTS = {
    "positive": [
        "Highly recommend this professor!",
        "Take this class if you can!",
        "One of my favorite professors.",
        "Worth the effort!",
        "Great learning experience.",
    ],
    "neutral": [
        "If you need this course, this is a fine option.",
        "Standard college experience.",
        "Take it if needed.",
        "It's what you make of it.",
        "Decent choice.",
    ],
    "negative": [
        "Try to avoid if possible.",
        "Not my best college experience.",
        "Could be better.",
        "Frustrating course overall.",
        "Not recommended unless required.",
    ],
}


def get_all_professors(db_path: str) -> list[str]:
    """Fetch all professor names from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT professor_name FROM professor_profiles ORDER BY professor_name")
    professors = [row[0] for row in cursor.fetchall()]
    conn.close()
    return professors


def generate_review(sentiment: str) -> str:
    """Generate a single review with specified sentiment."""
    # Pick a random topic category
    topic = random.choice(list(REVIEW_TEMPLATES[sentiment].keys()))
    templates = REVIEW_TEMPLATES[sentiment][topic]
    
    # Build review with main statement + closing
    main_statement = random.choice(templates)
    closing = random.choice(CLOSING_STATEMENTS[sentiment])
    
    review = f"{main_statement} {closing}"
    return review


def generate_professor_reviews(num_reviews: int = 4) -> dict[str, list[str]]:
    """Generate reviews for all professors."""
    professors = get_all_professors("data/seed/curriculum_advisor.db")
    reviews = {}
    
    for prof in professors:
        # Distribute sentiments: mostly positive/neutral with some negative for realism
        sentiments = ["positive"] * 2 + ["neutral"] * 1
        if num_reviews >= 4:
            sentiments += ["negative"] * 1
        if num_reviews >= 5:
            sentiments += [random.choice(["positive", "neutral"])]
        
        sentiments = sentiments[:num_reviews]
        random.shuffle(sentiments)
        
        prof_reviews = []
        for sentiment in sentiments:
            review = generate_review(sentiment)
            prof_reviews.append(review)
        
        reviews[prof] = prof_reviews
    
    return reviews


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic professor reviews for testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_synthetic_reviews.py
  python scripts/generate_synthetic_reviews.py --output-csv data/seed/professor_review_snippets.csv
  python scripts/generate_synthetic_reviews.py --reviews-per-professor 5
        """,
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="data/seed/professor_review_snippets.csv",
        help="Output CSV file path (default: data/seed/professor_review_snippets.csv)",
    )
    parser.add_argument(
        "--reviews-per-professor",
        type=int,
        default=4,
        help="Number of reviews to generate per professor (default: 4)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional)",
    )
    
    args = parser.parse_args()
    
    if args.seed is not None:
        random.seed(args.seed)
    
    print(f"Generating synthetic reviews...")
    print(f"  Reviews per professor: {args.reviews_per_professor}")
    print(f"  Output file: {args.output_csv}")
    
    # Generate reviews
    reviews_by_professor = generate_professor_reviews(args.reviews_per_professor)
    
    # Write to CSV
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    total_reviews = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["professor_name", "review_text"])
        
        for prof_name in sorted(reviews_by_professor.keys()):
            for review_text in reviews_by_professor[prof_name]:
                writer.writerow([prof_name, review_text])
                total_reviews += 1
    
    print(f"\n✓ Generated {total_reviews} reviews for {len(reviews_by_professor)} professors")
    print(f"  Output: {output_path.absolute()}")


if __name__ == "__main__":
    main()
