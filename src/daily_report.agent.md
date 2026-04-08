---
name: Daily news
description: Generates a daily news summary every morning
trigger:
  type: timer_trigger
  schedule: "0 0 15 * * *"
  run_on_startup: false
logger: true
execution_sandbox:
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT
---

Get the top news stories across local (Vancouver, Canada), national, and global categories. Summarize the key points of each story in 2-3 sentences.