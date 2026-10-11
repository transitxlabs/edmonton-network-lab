// Copyright 2026 TransitX Labs Inc. Licensed under Apache-2.0.
// Exhaustive trip scans in boarding rounds; the independent oracle is connection scan.
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int INF = 1000000000;
struct Edge { int to, seconds; };
struct Row { int stop, arr, dep, pickup, dropoff; };
struct Trip { int route; std::vector<Row> rows; };
struct Connection { int from, to, dep, arr, trip, position, pickup, dropoff; };
struct Leg { int parent, trip, from, to, dep, arr; };
struct Model {
    int ns = 0, np = 0, nr = 0;
    std::vector<std::vector<Edge>> walks, board_walks;
    std::vector<Trip> trips;
    std::vector<Connection> connections;
    std::vector<Leg> legs;
    std::vector<int> selected;
    std::string witness;
};
template<class T> T read(std::ifstream& in) {
    T x{}; in.read(reinterpret_cast<char*>(&x), sizeof(x));
    if (!in) throw std::runtime_error("Truncated model");
    return x;
}
}

extern "C" {
void* load_model(const char* filename) {
    try {
        std::ifstream in(filename, std::ios::binary);
        auto* m = new Model;
        if (read<int>(in) != 20261013) { delete m; return nullptr; }
        m->ns = read<int>(in); m->np = read<int>(in); m->nr = read<int>(in);
        int nt = read<int>(in);
        if (m->ns < 0 || m->np < m->ns || m->nr < 0 || nt < 0)
            throw std::runtime_error("Invalid dimensions");
        m->walks.resize(m->np); m->board_walks.resize(m->ns);
        for (auto& edges : m->walks) {
            int n = read<int>(in);
            for (int i=0; i<n; ++i) {
                Edge e{read<int>(in), read<int>(in)};
                if (e.to<0 || e.to>=m->np || e.seconds<0)
                    throw std::runtime_error("Invalid walking edge");
                edges.push_back(e);
            }
        }
        for (auto& edges : m->board_walks) {
            int n = read<int>(in);
            for (int i=0; i<n; ++i) {
                Edge e{read<int>(in), read<int>(in)};
                if (e.to<0 || e.to>=m->ns || e.seconds<0)
                    throw std::runtime_error("Invalid transfer edge");
                edges.push_back(e);
            }
        }
        for (int t=0; t<nt; ++t) {
            Trip trip; trip.route = read<int>(in);
            int n = read<int>(in);
            for (int i=0; i<n; ++i) {
                Row r{read<int>(in),read<int>(in),read<int>(in),read<int>(in),read<int>(in)};
                trip.rows.push_back(r);
            }
            for (int i=0; i+1<n; ++i) {
                auto a=trip.rows[i], b=trip.rows[i+1];
                m->connections.push_back({a.stop,b.stop,a.dep,b.arr,t,i,a.pickup,b.dropoff});
            }
            m->trips.push_back(std::move(trip));
        }
        std::stable_sort(m->connections.begin(),m->connections.end(),
            [](const Connection& a,const Connection& b) { return a.dep < b.dep; });
        return m;
    } catch (...) { return nullptr; }
}
void free_model(void* ptr) { delete static_cast<Model*>(ptr); }

// Returns number of rounds, or a negative error. No maximum transfer truncation.
int route_query_internal(void* ptr, int origin, int depart, int removed_route, int removed_trip,
                int* output, uint8_t* support, bool geometry) {
    auto& m = *static_cast<Model*>(ptr);
    if (origin<0 || origin>=m.np) return -1;
    const int limit=depart+3600;
    std::vector<int> board(m.ns,INF), bp(m.ns,-1), alight(m.ns,INF);
    std::vector<int> ap(m.ns,-1), result(m.np,INF), rp(m.np,-1);
    result[origin]=depart;
    for (auto e:m.walks[origin]) {
        if (e.seconds<=3600) {
            result[e.to]=depart+e.seconds;
            if (e.to<m.ns) board[e.to]=depart+e.seconds;
        }
    }
    m.legs.clear();
    std::vector<int> eligible;
    for (int t=0;t<static_cast<int>(m.trips.size());++t) {
        const auto& trip=m.trips[t];
        if (trip.route!=removed_route && t!=removed_trip && (geometry ||
            (trip.rows.back().arr>=depart && trip.rows.front().dep<=limit))) eligible.push_back(t);
    }
    int rounds=0;
    for (;;) {
        ++rounds;
        if (rounds>m.ns+1) return -2;
        auto previous=board, pp=bp;
        std::vector<int> improved;
        std::vector<uint8_t> marked(m.ns,0);
        for (int t:eligible) {
            const auto& trip=m.trips[t];
            int boarding=-1, parent=-1, bd=0, shift=INF;
            for (const auto& row:trip.rows) {
                // Alight before boarding at this occurrence: loop routes may repeat stops.
                int arrival=geometry ? row.arr+shift : row.arr;
                if (boarding>=0 && row.dropoff==0 && arrival<=limit && arrival<alight[row.stop]) {
                    alight[row.stop]=arrival;
                    ap[row.stop]=static_cast<int>(m.legs.size());
                    m.legs.push_back({parent,t,boarding,row.stop,bd,arrival});
                    if (!marked[row.stop]) { improved.push_back(row.stop); marked[row.stop]=1; }
                }
                if (geometry && row.pickup==0 && previous[row.stop]<INF &&
                    previous[row.stop]-row.dep<shift) {
                    boarding=row.stop; parent=pp[row.stop]; bd=previous[row.stop];
                    shift=previous[row.stop]-row.dep;
                } else if (!geometry && boarding<0 && row.pickup==0 && row.dep>=depart
                    && row.dep<=limit && previous[row.stop]<=row.dep) {
                    boarding=row.stop; parent=pp[row.stop]; bd=row.dep;
                }
            }
        }
        if (improved.empty()) break;
        for (int s:improved) {
            const int a=alight[s], path=ap[s];
            for (auto e:m.walks[s]) {
                int arrival=a+e.seconds;
                if (arrival<=limit && arrival<result[e.to]) {
                    result[e.to]=arrival; rp[e.to]=path;
                }
            }
            for (auto e:m.board_walks[s]) {
                int arrival=a+e.seconds;
                if (arrival<=limit && arrival<board[e.to]) {
                    board[e.to]=arrival; bp[e.to]=path;
                }
            }
        }
    }
    std::copy(result.begin(),result.end(),output);
    std::fill(support,support+m.nr,0);
    // A surviving selected optimum is a sufficient certificate for exact reuse.
    std::vector<uint8_t> visited(m.legs.size(),0);
    for (int p=m.ns;p<m.np;++p) {
        for (int leg=rp[p]; leg>=0 && !visited[leg]; leg=m.legs[leg].parent) {
            visited[leg]=1; support[m.trips[m.legs[leg].trip].route]=1;
        }
    }
    m.selected=std::move(rp);
    return rounds;
}
int route_query(void* ptr, int origin, int depart, int removed_route, int removed_trip,
                int* output, uint8_t* support) {
    return route_query_internal(ptr,origin,depart,removed_route,removed_trip,output,support,false);
}
int geometry_query(void* ptr,int origin,int* output,uint8_t* support) {
    return route_query_internal(ptr,origin,0,-1,-1,output,support,true);
}
const char* query_witness(void* ptr) {
    auto& m=*static_cast<Model*>(ptr); std::ostringstream s;
    std::vector<uint8_t> used(m.legs.size(),0);
    for(int p=m.ns;p<m.np;++p)
        for(int i=m.selected[p];i>=0 && !used[i];i=m.legs[i].parent)used[i]=1;
    std::vector<int> remap(m.legs.size(),-1); int count=0;
    for(size_t i=0;i<used.size();++i)if(used[i])remap[i]=count++;
    s << "{\"legs\":["; bool first=true;
    for (size_t i=0;i<m.legs.size();++i) {
        if(!used[i])continue;
        if(!first) { s << ','; }
        first=false;
        auto l=m.legs[i];
        s << '[' << (l.parent<0 ? -1 : remap[l.parent]) << ',' << l.trip << ',' << l.from << ',' << l.to << ','
          << l.dep << ',' << l.arr << ']';
    }
    s << "],\"destination_leg\":[";
    for (int i=m.ns;i<m.np;++i) { if(i>m.ns)s << ',';
        s << (m.selected[i]<0 ? -1 : remap[m.selected[i]]); }
    s << "]}"; m.witness=s.str(); return m.witness.c_str();
}

// Independently written departure-ordered connection scan. No boarding rounds or parents.
int oracle_query(void* ptr,int origin,int depart,int removed_route,int removed_trip,int* output) {
    auto& m=*static_cast<Model*>(ptr); const int limit=depart+3600;
    std::vector<int> earliest(m.ns,INF), destination(m.np,INF), raw_alight(m.ns,INF);
    std::vector<int> aboard_from(m.trips.size(),INF);
    destination[origin]=depart;
    for (const Edge& w:m.walks[origin]) {
        if (w.seconds<=3600) {
            destination[w.to]=depart+w.seconds;
            if(w.to<m.ns)earliest[w.to]=depart+w.seconds;
        }
    }
    auto begin=std::lower_bound(m.connections.begin(),m.connections.end(),depart,
        [](const Connection& c,int t){return c.dep<t;});
    for (auto it=begin;it!=m.connections.end() && it->dep<=limit;) {
        auto end=it;
        while(end!=m.connections.end() && end->dep==it->dep)++end;
        // Fixed point within ties handles zero-duration connections without order dependence.
        bool changed;
        do {
            changed=false;
            for(auto c=it;c!=end;++c) {
                if(m.trips[c->trip].route==removed_route || c->trip==removed_trip)continue;
                if (c->position<aboard_from[c->trip] && c->pickup==0 && earliest[c->from]<=c->dep) {
                    aboard_from[c->trip]=c->position; changed=true;
                }
                if(aboard_from[c->trip]>c->position || c->dropoff!=0 || c->arr>limit
                    || c->arr>=raw_alight[c->to])continue;
                raw_alight[c->to]=c->arr;
                for (const Edge& w:m.walks[c->to]) {
                    int a=c->arr+w.seconds;
                    if(a<=limit && a<destination[w.to]) {destination[w.to]=a;changed=true;}
                }
                for (const Edge& w:m.board_walks[c->to]) {
                    int ready=c->arr+w.seconds;
                    if(ready<=limit && ready<earliest[w.to]) {earliest[w.to]=ready;changed=true;}
                }
            }
        } while(changed);
        it=end;
    }
    std::copy(destination.begin(),destination.end(),output);return 0;
}
}
