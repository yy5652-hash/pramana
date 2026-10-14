# Pramana: common tasks. `make demo` builds the sample course and starts the app.
PY := .venv/bin/python
COURSE ?= mechanics

.PHONY: setup fetch ingest bank course serve demo test eval replay clean-kb

setup:            ## create the virtual environment and install everything
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -e ".[eval,dev]"

fetch:            ## download the openly licensed course files (about 470 MB)
	$(PY) -m pramana.cli fetch $(COURSE)

ingest:           ## read the files into the knowledge base and build the concept map
	$(PY) -m pramana.cli ingest $(COURSE)

bank:             ## generate and verify the question bank
	$(PY) -m pramana.cli bank $(COURSE) --rounds 2

serve:            ## run the web app on http://127.0.0.1:8000
	$(PY) -m pramana.cli serve

demo: fetch course serve

test:             ## unit tests (no model, no network)
	$(PY) -m pytest -q

eval:             ## full evaluation; writes evaluation/results/*.json
	$(PY) -m pramana.cli ingest $(COURSE) --no-vision --no-organise --as $(COURSE)-textonly
	$(PY) -m evaluation.retrieval --course $(COURSE) --ablation $(COURSE)-textonly
	$(PY) -m evaluation.ablation --course $(COURSE) --no-vision $(COURSE)-textonly
	$(PY) -m evaluation.grounding --course $(COURSE)
	$(PY) -m evaluation.ragas_eval
	$(PY) -m evaluation.lessons --course $(COURSE)
	$(PY) -m evaluation.simulate --course $(COURSE) --students 40
	$(PY) -m evaluation.report --course $(COURSE)

course:           ## build the sample course from the committed caches (no API key, no model calls)
	PRAMANA_LLM_MODE=replay $(MAKE) ingest bank

replay:           ## rebuild everything from the committed caches, without an API key
	PRAMANA_LLM_MODE=replay $(MAKE) ingest bank eval

clean-kb:         ## delete the built knowledge base (caches are kept)
	rm -rf data/kb data/work
