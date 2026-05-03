# Final Presentation Max-Points Plan

This file lists the implementation work that will have the biggest impact on the final presentation rubric. The goal is to make the demo technically strong, complete, intuitive, and easy to defend in Q&A.

## Rubric Targets

- Technical soundness and model use: clearly show why the system is GenAI-based and what the backend is doing.
- Problem fit and impact: show that the app solves a real advising problem, not just a generic recommendation demo.
- Execution and completeness: demonstrate a coherent end-to-end workflow with no dead ends.
- Design and user experience: make the flow easy to understand in under a minute.
- Demo quality: have a stable scripted demo that works every time.

## Highest-Priority Implementation Work

1. Make the main user flow feel conversational or guided.
- Add a chat-style onboarding flow or step-by-step assistant panel.
- Let the user provide major, completed courses, transcript text, preferences, and goals in a single guided flow.
- Show the system response in natural language, not only as a raw form submission result.

2. Add a visible baseline vs sentiment-aware mode.
- Provide a toggle or comparison view for baseline recommendations and sentiment-aware recommendations.
- Show what changed, why it changed, and which professor sentiment signals influenced the ranking.
- Include a short explanation string for each recommendation set.

3. Strengthen the recommendation explanation layer.
- Explain degree fit, requirement-group fit, schedule fit, and sentiment fit for each course.
- Surface prerequisite-safe filtering in the explanation so the audience can see that invalid courses are blocked.
- Mention when blocked windows, completed courses, or unit caps affected the output.

4. Make the demo obviously degree-aware.
- Show degree selection from the available degree list.
- Show progress toward degree requirements in a clean progress indicator.
- Make requirement-group organization visible so the output reads like an academic plan.

5. Make the schedule and constraint handling visible.
- Show day/time scheduling in a clear layout.
- Show that time conflicts are removed automatically.
- Show blocked time windows and semester unit caps affecting the final selection.

6. Improve sentiment transparency.
- Display professor name, sentiment-related rating data, and source metadata when available.
- Make it clear when the system uses seed/simulated sentiment versus live RMP data.
- Add a short disclaimer about responsible use of review data.

7. Make the UI polished enough for a live demo.
- Improve layout hierarchy so the user sees input, results, schedule, and progress in the right order.
- Add clear empty states, loading states, and error states.
- Make sure mobile and desktop layouts both look deliberate.

8. Add a stable demo script with predictable scenarios.
- Prepare one scenario that shows a normal recommendation flow.
- Prepare one scenario that shows sentiment changing the ranking.
- Prepare one scenario that shows blocked windows or completed coursework changing the result.

9. Add lightweight validation and guardrails.
- Prevent empty or invalid submissions.
- Handle missing data gracefully.
- Make sure the app never returns prerequisite-unsafe recommendations.

10. Make the system easy to explain during Q&A.
- Be able to describe the data pipeline, ranking logic, and constraint filtering in plain language.
- Be able to explain what the LLM does and what is deterministic.
- Be able to explain the limitations of sentiment data and the fallback path.

## Recommended Build Order

1. Guided conversational flow.
2. Baseline vs sentiment-aware toggle.
3. Better explanations for every recommendation.
4. Clean degree progress and schedule visualization.
5. UI polish, loading states, and error handling.
6. Demo scenario preparation and stability checks.

## What Not To Spend Time On Before Presentation

- Final report writing details.
- Overengineering the ranking model.
- Adding new data sources unless they directly improve the demo.
- Expanding to unrelated features outside course planning.

## Demo Success Criteria

- A reviewer can understand the problem and solution within 30 seconds.
- The system clearly shows a working GenAI-backed workflow.
- The system makes valid, degree-aware recommendations without prerequisite violations.
- The demo includes at least one visible comparison or tradeoff point.
- The presentation can answer why the system matters and what is novel about it.