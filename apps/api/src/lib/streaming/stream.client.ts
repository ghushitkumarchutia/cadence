export interface EventEnvelope<T = unknown> {
  eventId: string;
  eventType: string;
  schemaVersion: string;
  timestamp: string;
  orgId: string;
  projectId: string;
  payload: T;
}

export type EventHandler = (message: EventEnvelope, messageId: string) => Promise<void>;

export interface StreamClient {
  publish(stream: string, message: EventEnvelope): Promise<string>;
  subscribe(
    stream: string,
    group: string,
    consumer: string,
    handler: EventHandler,
  ): Promise<void>;
  acknowledge(stream: string, group: string, id: string): Promise<void>;
  ensureGroup(stream: string, group: string): Promise<void>;
}
