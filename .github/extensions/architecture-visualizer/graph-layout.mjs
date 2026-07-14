const DEFAULT_OPTIONS = {
    nodeWidth: 204,
    nodeHeight: 76,
    rankGap: 40,
    nodeGap: 28,
    marginX: 30,
    marginTop: 72,
    marginBottom: 34,
    lanePaddingX: 14,
    lanePaddingY: 18,
};

function mean(values) {
    return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function roundedPolylinePath(points, radius = 12) {
    if (points.length < 2) {
        throw new Error("At least two points are required to route an edge");
    }

    const [start, ...rest] = points;
    const commands = [`M ${start.x.toFixed(1)} ${start.y.toFixed(1)}`];

    for (let index = 1; index < points.length - 1; index += 1) {
        const previous = points[index - 1];
        const current = points[index];
        const next = points[index + 1];
        const previousLength = Math.hypot(current.x - previous.x, current.y - previous.y);
        const nextLength = Math.hypot(next.x - current.x, next.y - current.y);
        const cornerRadius = Math.min(radius, previousLength / 2, nextLength / 2);

        if (cornerRadius <= 0) {
            commands.push(`L ${current.x.toFixed(1)} ${current.y.toFixed(1)}`);
            continue;
        }

        const beforeCorner = {
            x: current.x - ((current.x - previous.x) / previousLength) * cornerRadius,
            y: current.y - ((current.y - previous.y) / previousLength) * cornerRadius,
        };
        const afterCorner = {
            x: current.x + ((next.x - current.x) / nextLength) * cornerRadius,
            y: current.y + ((next.y - current.y) / nextLength) * cornerRadius,
        };

        commands.push(`L ${beforeCorner.x.toFixed(1)} ${beforeCorner.y.toFixed(1)}`);
        commands.push(
            `Q ${current.x.toFixed(1)} ${current.y.toFixed(1)}, ${afterCorner.x.toFixed(1)} ${afterCorner.y.toFixed(1)}`,
        );
    }

    const end = rest.at(-1);
    commands.push(`L ${end.x.toFixed(1)} ${end.y.toFixed(1)}`);
    return commands.join(" ");
}

function groupedByRank(graph, layerRank) {
    const ranks = graph.layers.map(() => []);

    graph.nodes.forEach((node, index) => {
        const rank = layerRank.get(node.layer);
        if (rank === undefined) {
            throw new Error(`Node ${node.id} references unknown layer ${node.layer}`);
        }
        ranks[rank].push({ ...node, originalIndex: index, rank });
    });

    return ranks.map((nodes) => nodes.map((node) => node.id));
}

function rankMetadata(graph, ranks) {
    const nodeById = new Map(
        graph.nodes.map((node, index) => [node.id, { ...node, originalIndex: index }]),
    );
    const rankById = new Map();

    ranks.forEach((rank, rankIndex) => {
        rank.forEach((nodeId) => {
            rankById.set(nodeId, rankIndex);
        });
    });

    return { nodeById, rankById };
}

function orderById(ranks) {
    const order = new Map();

    ranks.forEach((rank, rankIndex) => {
        rank.forEach((nodeId, orderIndex) => {
            order.set(nodeId, {
                rank: rankIndex,
                index: orderIndex,
                normalized: (orderIndex + 0.5) / rank.length,
            });
        });
    });

    return order;
}

function sortedRank(rank, graph, rankById, nodeById, order, direction) {
    const scored = rank.map((nodeId, fallbackIndex) => {
        const neighborScores = graph.edges
            .filter((edge) => {
                if (direction === "forward") {
                    return edge.to === nodeId && rankById.get(edge.from) < rankById.get(nodeId);
                }
                return edge.from === nodeId && rankById.get(edge.to) > rankById.get(nodeId);
            })
            .map((edge) => {
                const neighborId = direction === "forward" ? edge.from : edge.to;
                return order.get(neighborId)?.normalized;
            })
            .filter((score) => score !== undefined);

        return {
            nodeId,
            fallbackIndex,
            originalIndex: nodeById.get(nodeId).originalIndex,
            score: neighborScores.length ? mean(neighborScores) : undefined,
        };
    });

    scored.sort((left, right) => {
        if (left.score !== undefined && right.score !== undefined && left.score !== right.score) {
            return left.score - right.score;
        }
        if (left.score !== undefined && right.score === undefined) {
            return -1;
        }
        if (left.score === undefined && right.score !== undefined) {
            return 1;
        }
        return left.originalIndex - right.originalIndex || left.fallbackIndex - right.fallbackIndex;
    });

    return scored.map((item) => item.nodeId);
}

function reduceCrossings(graph, initialRanks, metadata) {
    const ranks = initialRanks.map((rank) => [...rank]);

    for (let iteration = 0; iteration < 8; iteration += 1) {
        let order = orderById(ranks);
        for (let rankIndex = 1; rankIndex < ranks.length; rankIndex += 1) {
            ranks[rankIndex] = sortedRank(
                ranks[rankIndex],
                graph,
                metadata.rankById,
                metadata.nodeById,
                order,
                "forward",
            );
            order = orderById(ranks);
        }

        order = orderById(ranks);
        for (let rankIndex = ranks.length - 2; rankIndex >= 0; rankIndex -= 1) {
            ranks[rankIndex] = sortedRank(
                ranks[rankIndex],
                graph,
                metadata.rankById,
                metadata.nodeById,
                order,
                "backward",
            );
            order = orderById(ranks);
        }
    }

    return ranks;
}

function rankWidth(rank, options) {
    return rank.length * options.nodeWidth + Math.max(0, rank.length - 1) * options.nodeGap;
}

function assignNodeGeometry(graph, ranks, nodeById, options) {
    const maxRankWidth = Math.max(...ranks.map((rank) => rankWidth(rank, options)));
    const width = options.marginX * 2 + maxRankWidth;
    const height =
        options.marginTop +
        graph.layers.length * options.nodeHeight +
        Math.max(0, graph.layers.length - 1) * options.rankGap +
        options.marginBottom;

    const nodes = [];
    const layoutById = new Map();

    ranks.forEach((rank, rankIndex) => {
        const y = options.marginTop + rankIndex * (options.nodeHeight + options.rankGap);
        const firstX = options.marginX + (maxRankWidth - rankWidth(rank, options)) / 2;

        rank.forEach((nodeId, orderIndex) => {
            const node = {
                ...nodeById.get(nodeId),
                rank: rankIndex,
                order: orderIndex,
                x: firstX + orderIndex * (options.nodeWidth + options.nodeGap),
                y,
                width: options.nodeWidth,
                height: options.nodeHeight,
            };
            nodes.push(node);
            layoutById.set(node.id, node);
        });
    });

    return { nodes, layoutById, width, height };
}

function portMap(edges, layoutById, direction) {
    const grouped = new Map();
    for (const edge of edges) {
        const key = direction === "outgoing" ? edge.from : edge.to;
        if (!grouped.has(key)) {
            grouped.set(key, []);
        }
        grouped.get(key).push(edge);
    }

    const ports = new Map();
    for (const [nodeId, nodeEdges] of grouped.entries()) {
        nodeEdges.sort((left, right) => {
            const leftOther = layoutById.get(direction === "outgoing" ? left.to : left.from);
            const rightOther = layoutById.get(direction === "outgoing" ? right.to : right.from);
            return leftOther.x - rightOther.x || left.label.localeCompare(right.label);
        });

        const node = layoutById.get(nodeId);
        nodeEdges.forEach((edge, index) => {
            const portX = node.x + ((index + 1) * node.width) / (nodeEdges.length + 1);
            ports.set(edge.from + "->" + edge.to + ":" + direction, portX);
        });
    }

    return ports;
}

function sameRankEdge(edge, index, from, to) {
    const routeAbove = from.rank < 2;
    const routeY = routeAbove ? from.y - 28 : from.y + from.height + 28;
    const start = {
        x: from.x + from.width / 2,
        y: routeAbove ? from.y : from.y + from.height,
    };
    const end = {
        x: to.x + to.width / 2,
        y: routeAbove ? to.y : to.y + to.height,
    };
    const labelY = routeY + (routeAbove ? -4 : 12) + ((index % 2) * 8);

    return {
        d: roundedPolylinePath([start, { x: start.x, y: routeY }, { x: end.x, y: routeY }, end]),
        labelX: (start.x + end.x) / 2,
        labelY,
    };
}

function crossRankEdge(edge, index, from, to, outgoingPorts, incomingPorts) {
    const key = edge.from + "->" + edge.to;
    const forward = from.rank <= to.rank;
    const start = {
        x: outgoingPorts.get(key + ":outgoing") ?? from.x + from.width / 2,
        y: forward ? from.y + from.height : from.y,
    };
    const end = {
        x: incomingPorts.get(key + ":incoming") ?? to.x + to.width / 2,
        y: forward ? to.y : to.y + to.height,
    };
    const midY = (start.y + end.y) / 2 + ((index % 5) - 2) * 4;

    return {
        d: roundedPolylinePath([start, { x: start.x, y: midY }, { x: end.x, y: midY }, end]),
        labelX: (start.x + end.x) / 2,
        labelY: midY - 7,
    };
}

function assignEdgeGeometry(graph, layoutById) {
    const outgoingPorts = portMap(graph.edges, layoutById, "outgoing");
    const incomingPorts = portMap(graph.edges, layoutById, "incoming");

    return graph.edges.map((edge, index) => {
        const from = layoutById.get(edge.from);
        const to = layoutById.get(edge.to);
        const route =
            from.rank === to.rank
                ? sameRankEdge(edge, index, from, to)
                : crossRankEdge(edge, index, from, to, outgoingPorts, incomingPorts);

        return {
            ...edge,
            d: route.d,
            labelX: Number(route.labelX.toFixed(1)),
            labelY: Number(route.labelY.toFixed(1)),
            labelWidth: clamp(edge.label.length * 6.4 + 16, 54, 156),
        };
    });
}

function laneGeometry(graph, options, width) {
    return graph.layers.map((layer, rankIndex) => {
        const y =
            options.marginTop +
            rankIndex * (options.nodeHeight + options.rankGap) -
            options.lanePaddingY;

        return {
            ...layer,
            x: options.lanePaddingX,
            y,
            width: width - options.lanePaddingX * 2,
            height: options.nodeHeight + options.lanePaddingY * 2,
            labelX: options.lanePaddingX + 14,
            labelY: y + 24,
        };
    });
}

export function layoutLayeredGraph(graph, options = {}) {
    const resolvedOptions = { ...DEFAULT_OPTIONS, ...options };
    const layerRank = new Map(graph.layers.map((layer, index) => [layer.id, index]));
    const initialRanks = groupedByRank(graph, layerRank);
    const metadata = rankMetadata(graph, initialRanks);
    const ranks = reduceCrossings(graph, initialRanks, metadata);
    const nodeGeometry = assignNodeGeometry(
        graph,
        ranks,
        metadata.nodeById,
        resolvedOptions,
    );

    return {
        ...graph,
        layout: {
            width: nodeGeometry.width,
            height: nodeGeometry.height,
            nodeWidth: resolvedOptions.nodeWidth,
            nodeHeight: resolvedOptions.nodeHeight,
            algorithm: "layered-barycentric",
            direction: "top-to-bottom",
        },
        lanes: laneGeometry(graph, resolvedOptions, nodeGeometry.width),
        nodes: nodeGeometry.nodes,
        edges: assignEdgeGeometry(graph, nodeGeometry.layoutById),
    };
}
