FROM eclipse-temurin:21-jdk AS builder
RUN apt-get update && apt-get install -y protobuf-compiler wget

WORKDIR /app
RUN wget https://repo1.maven.org/maven2/org/zeromq/jeromq/0.5.4/jeromq-0.5.4.jar
RUN wget https://repo1.maven.org/maven2/com/google/protobuf/protobuf-java/3.25.1/protobuf-java-3.25.1.jar

COPY mensagens.proto .
COPY src/main/java/cliente.java .

RUN protoc --java_out=. mensagens.proto
RUN javac -cp "jeromq-0.5.4.jar:protobuf-java-3.25.1.jar:." cliente.java sistema/*.java

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=builder /app /app
CMD ["java", "-cp", "jeromq-0.5.4.jar:protobuf-java-3.25.1.jar:.", "cliente"]