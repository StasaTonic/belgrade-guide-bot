#CURRENT_DIR = $(shell pwd)
PROJECT_NAME = tg_ai_bot
CURRENT_DIR = C:\AI_AGENTS\tg_ai_bot_template
DATA_DIR = ${CURRENT_DIR}/data/db

prepare-dirs:
	mkdir -p ${CURRENT_DIR}/data/phoenix_data || true
	mkdir -p ${CURRENT_DIR}/data/db || true


build: prepare-dirs
	docker build -f Dockerfile \
		-t ${PROJECT_NAME}_tg:latest .

run: stop phoenix
	docker run -it --rm \
		--env-file ${CURRENT_DIR}/.env  \
		--network tg_ai_bot_template_default \
		-v ${CURRENT_DIR}/src:/srv/src \
		-v ${CURRENT_DIR}/scripts:/srv/scripts \
		-v ${CURRENT_DIR}/data:/srv/data \
	    --name ${PROJECT_NAME}_container_tg \
		${PROJECT_NAME}_tg:latest
stop:
	docker rm -f ${PROJECT_NAME}_container_tg || true

phoenix:
	docker compose up phoenix -d

eval:
	docker run --rm \
		--env-file ${CURRENT_DIR}/.env \
		-v ${CURRENT_DIR}/src:/srv/src \
		-v ${CURRENT_DIR}/evals:/srv/evals \
		${PROJECT_NAME}_tg:latest python evals/eval_json_extraction.py



chat: phoenix
	docker run -it --rm \
		--env-file ${CURRENT_DIR}/.env  \
		--network tg_ai_bot_template_default \
		-v ${CURRENT_DIR}/src:/srv/src \
		-v ${CURRENT_DIR}/scripts:/srv/scripts \
		-v ${CURRENT_DIR}/data:/srv/data \
	    --name ${PROJECT_NAME}_container_tg \
		${PROJECT_NAME}_tg:latest python3.12 scripts/chat.py
history:
	docker exec ${PROJECT_NAME}_container_tg python /srv/scripts/db_history.py
