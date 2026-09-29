name: Modern City Bot

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  bot:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v6

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Start Modern City Bot
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
        run: python bot.py
