import asyncio

from bs4 import BeautifulSoup

from src.ai_agent import dialog_router
from src.db import init_db

USER = {'user_name': 'average_human', 'name': 'Average Human'}

MAX_TURNS = 10

async def main():
    await init_db()
    human_input = input("User 👤: ")
    for k in range(MAX_TURNS):
        answer = await dialog_router(human_input=human_input, user=USER)
        if answer['is_html']:
            text = BeautifulSoup(answer['answer'], 'html.parser').get_text()
            print(f"Agent 🤖: {text}")
            break
        else:
            print(f"Agent 🤖: {answer['answer']}")
            human_input = input("User 👤: ")
            print('\n..............\n')
        if k == MAX_TURNS - 1:
            print("Conversation length overflow")


if __name__ == '__main__':
    asyncio.run(main())
