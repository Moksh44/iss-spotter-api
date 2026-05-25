FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /tmp/mpl_cache && chmod -R 777 /tmp/mpl_cache
ENV MPLCONFIGDIR=/tmp/mpl_cache
EXPOSE 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app:app"]