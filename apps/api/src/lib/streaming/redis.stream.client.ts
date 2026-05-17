import { redis, STREAM_MAX_LEN } from "../redis/client.js";
import type { StreamClient, EventEnvelope, EventHandler } from "./stream.client.js";

export class RedisStreamClient implements StreamClient {
  async publish(stream: string, message: EventEnvelope): Promise<string> {
    const id = await redis.xadd(
      stream,
      "MAXLEN",
      "~",
      String(STREAM_MAX_LEN),
      "*",
      "data",
      JSON.stringify(message),
    );
    return id!;
  }

  async ensureGroup(stream: string, group: string): Promise<void> {
    try {
      await redis.xgroup("CREATE", stream, group, "0", "MKSTREAM");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (!message.includes("BUSYGROUP")) throw err;
    }
  }

  async subscribe(
    stream: string,
    group: string,
    consumer: string,
    handler: EventHandler,
  ): Promise<void> {
    await this.ensureGroup(stream, group);

    const processLoop = async () => {
      while (true) {
        try {
          const results = await redis.xreadgroup(
            "GROUP",
            group,
            consumer,
            "COUNT",
            "10",
            "BLOCK",
            "5000",
            "STREAMS",
            stream,
            ">",
          );

          if (!results) continue;

          for (const streamData of results as [string, [string, string[]][]][]) {
            const messages = streamData[1];
            for (const msg of messages) {
              const id = msg[0];
              const fields = msg[1];
              const raw = fields[1];
              if (!raw) continue;
              const envelope = JSON.parse(raw) as EventEnvelope;
              try {
                await handler(envelope, id);
                await this.acknowledge(stream, group, id);
              } catch {
                continue;
              }
            }
          }
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }
      }
    };

    processLoop();
  }

  async acknowledge(stream: string, group: string, id: string): Promise<void> {
    await redis.xack(stream, group, id);
  }
}

export const streamClient = new RedisStreamClient();
