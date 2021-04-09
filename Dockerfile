FROM gopalkrishnaps/intellij:2020.1

WORKDIR /opt

COPY entrypoint.sh /entrypoint.sh
COPY requirements.txt /requirements.txt
COPY analyze_inspections.py /analyze_inspections.py

RUN chmod +x /entrypoint.sh && \
    chmod +x /analyze_inspections.py && \
    pip3 install -r /requirements.txt

ENTRYPOINT ["/entrypoint.sh"]
