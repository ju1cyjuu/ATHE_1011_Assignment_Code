FROM python:3.11
WORKDIR /asg
COPY . .
RUN pip install -r requirements.txt
ENV DISPLAY=host.docker.internal:0.0
CMD ["python","Assignment1.py"]