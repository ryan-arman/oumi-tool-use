# tau2 retail evaluators (Oumi judges)

Both are **Judge** evaluators. Each reads one metadata field that
`convert_tasks.py` writes on every row.

## 1. tau2 retail - Correct changes

Approximates tau2's store check: the store ends up right exactly when the
agent's successful change calls match the gold ones.

- **What should the judge evaluate?** Whether the changes the assistant made to the store match the expected actions exactly.
- **Conversation system message:** off (the policy isn't needed to compare calls)
- **Metadata fields:** Key `expected_actions`, Display Title `Expected actions`
- **Judgments:**
  - **Match** (score 1): Every expected action appears as a tool call whose result is not an error, with the same tool and the same argument values. Compare every ID (order, item, payment method, user) character by character, and compare text values such as a cancellation reason exactly. Apart from the expected actions, the assistant made no other successful call to cancel_pending_order, exchange_delivered_order_items, modify_pending_order_address, modify_pending_order_items, modify_pending_order_payment, modify_user_address, return_delivered_order_items or transfer_to_human_agents. Calls whose result is an error don't count either way. If the expected actions are "None", Match only when no such call succeeded.
  - **Mismatch** (score 0): Anything else: an expected action is missing, has any different argument value, or an extra change or transfer succeeded.

## 2. tau2 retail - Required statements

The same kind of check tau2 runs with an LLM (its `nl_assertions`).

- **What should the judge evaluate?** Whether the assistant's messages to the user satisfy every required statement.
- **Conversation system message:** off
- **Metadata fields:** Key `required_statements`, Display Title `Required statements`
- **Judgments:**
  - **Pass** (score 1): Every required statement holds for what the assistant told the user, or the required statements are "None.".
  - **Fail** (score 0): At least one required statement does not hold.
