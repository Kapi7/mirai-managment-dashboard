#!/usr/bin/env python3
"""
Test Emma's responses for various support scenarios.
Run this to verify Emma generates appropriate, policy-aware responses.
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# Check for OpenAI API key
if not os.getenv("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set. Set it to run simulations.")
    print("Export your key: export OPENAI_API_KEY='your-key-here'")
    sys.exit(1)

from emma_agent import respond_as_emma

# Test scenarios
TEST_SCENARIOS = [
    {
        "name": "Tracking Inquiry - Recent Order",
        "customer_email": "tuyen@example.com",
        "customer_name": "Tuyen Nguyen",
        "message": "Hi can you check for my order I am still not received yet",
        "expected_elements": [
            "3-5 business days",  # Processing time
            "7-14 business days",  # Shipping time
            "tracking",
            "South Korea"  # Shipping origin
        ],
        "should_not_contain": [
            "tomorrow",  # Unrealistic promise
            "same day",
            "expedite"  # Can't expedite
        ]
    },
    {
        "name": "Return Request",
        "customer_email": "jane@example.com",
        "customer_name": "Jane Smith",
        "message": "I want to return a product I bought last month. How do I do this?",
        "expected_elements": [
            "180",  # 180-day return policy
            "unopened",
            "support@mirai-skin.com",
            "return shipping"
        ],
        "should_not_contain": []
    },
    {
        "name": "Damaged Item",
        "customer_email": "bob@example.com",
        "customer_name": "Bob Wilson",
        "message": "My order arrived but one of the products was damaged. The glass jar was cracked.",
        "expected_elements": [
            "photo",  # Should ask for photos
            "replacement",
            "refund"
        ],
        "should_not_contain": [
            "return shipping"  # Customer shouldn't pay for damaged items
        ]
    },
    {
        "name": "Customs Duties Question",
        "customer_email": "maria@example.com",
        "customer_name": "Maria Garcia",
        "message": "Do I have to pay customs fees when ordering to the United States?",
        "expected_elements": [
            "customs",
            "customer",  # Customer responsibility
            "duties"
        ],
        "should_not_contain": [
            "we pay",  # We don't pay customs
            "we cover",
            "included"  # Not included
        ]
    },
    {
        "name": "Product Question (Sales)",
        "customer_email": "alex@example.com",
        "customer_name": "Alex",
        "message": "What's a good moisturizer for dry skin? I'm looking for something hydrating.",
        "expected_elements": [],  # Just check it doesn't crash
        "should_not_contain": []
    },
    {
        "name": "Refund Timeline",
        "customer_email": "chris@example.com",
        "customer_name": "Chris",
        "message": "I returned my items a week ago. When will I get my refund?",
        "expected_elements": [
            "10 business days"
        ],
        "should_not_contain": []
    }
]


def run_simulation(scenario):
    """Run a single simulation and check the response."""
    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario['name']}")
    print(f"{'='*60}")
    print(f"Customer: {scenario['customer_name']} ({scenario['customer_email']})")
    print(f"Message: {scenario['message']}")
    print("-" * 60)

    try:
        response = respond_as_emma(
            first_name=scenario['customer_name'].split()[0] if scenario['customer_name'] else "",
            cart_items=[],
            customer_msg=scenario['message'],
            history=[],
            first_contact=False,
            geo=None,
            style_mode="soft",
            customer_email=scenario['customer_email']
        )

        print(f"\nEMMA'S RESPONSE:\n{response}")
        print("-" * 60)

        # Check expected elements
        response_lower = response.lower()
        missing = []
        for element in scenario.get('expected_elements', []):
            if element.lower() not in response_lower:
                missing.append(element)

        # Check should not contain
        found_bad = []
        for bad in scenario.get('should_not_contain', []):
            if bad.lower() in response_lower:
                found_bad.append(bad)

        # Report results
        print("\nCHECKS:")
        if missing:
            print(f"  MISSING expected elements: {missing}")
        else:
            print(f"  All expected elements found")

        if found_bad:
            print(f"  FOUND unwanted elements: {found_bad}")
        else:
            print(f"  No unwanted elements found")

        passed = len(missing) == 0 and len(found_bad) == 0
        print(f"\n  STATUS: {'PASS' if passed else 'NEEDS REVIEW'}")

        return {
            "name": scenario['name'],
            "passed": passed,
            "response": response,
            "missing": missing,
            "found_bad": found_bad
        }

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return {
            "name": scenario['name'],
            "passed": False,
            "error": str(e)
        }


def test_with_hints():
    """Test the user hints feature."""
    print(f"\n{'='*60}")
    print("TESTING USER HINTS FEATURE")
    print(f"{'='*60}")

    message = "I want to return a product"

    # Without hints
    print("\n--- WITHOUT HINTS ---")
    response1 = respond_as_emma(
        first_name="Test",
        cart_items=[],
        customer_msg=message,
        history=[],
        first_contact=False,
        customer_email="test@example.com"
    )
    print(f"Response: {response1[:200]}...")

    # With hints
    print("\n--- WITH HINTS: 'Offer a 10% discount code as a goodwill gesture' ---")
    response2 = respond_as_emma(
        first_name="Test",
        cart_items=[],
        customer_msg=message,
        history=[],
        first_contact=False,
        customer_email="test@example.com",
        user_hints="Offer a 10% discount code as a goodwill gesture"
    )
    print(f"Response: {response2[:300]}...")

    # Check if discount was mentioned
    if "discount" in response2.lower() or "%" in response2:
        print("\n  HINTS TEST: PASS - Discount mentioned in response")
    else:
        print("\n  HINTS TEST: NEEDS REVIEW - Discount may not be in response")


def main():
    print("="*60)
    print("EMMA RESPONSE SIMULATION TEST")
    print("Testing policy-aware responses for support scenarios")
    print("="*60)

    results = []

    for scenario in TEST_SCENARIOS:
        result = run_simulation(scenario)
        results.append(result)

    # Test hints feature
    test_with_hints()

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for r in results if r.get('passed', False))
    total = len(results)

    print(f"Passed: {passed}/{total}")

    if passed < total:
        print("\nScenarios needing review:")
        for r in results:
            if not r.get('passed', False):
                print(f"  - {r['name']}")
                if r.get('missing'):
                    print(f"    Missing: {r['missing']}")
                if r.get('found_bad'):
                    print(f"    Found unwanted: {r['found_bad']}")

    print(f"\n{'='*60}")
    print("Test complete. Review responses above for quality.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
