import tensorflow as tf

import numpy as np
import gym
from gym import wrappers

from replay_buffer import ReplayBuffer

import argparse
import pprint as pp

from TD3_keras_agent import TD3


# ===========================
#   Tensorflow Summary Ops
# ===========================

def build_summaries():
    episode_reward = tf.Variable(0.)
    tf.summary.scalar("Reward", episode_reward)
    episode_ave_max_q = tf.Variable(0.)
    tf.summary.scalar("Qmax Value", episode_ave_max_q)

    summary_vars = [episode_reward, episode_ave_max_q]
    summary_ops = tf.summary.merge_all()

    return summary_ops, summary_vars

def update_policy(sess, env, env_test, args, agent, replay_buffer, action_noise, update_num ):
    for ite in range(update_num):
        s_batch, a_batch, r_batch, t_batch, s2_batch = \
            replay_buffer.sample_batch(int(args['minibatch_size']))

        noise_clip = 0.5
        noise = np.clip(np.random.normal(0, action_noise, size=(int(args['minibatch_size']), agent.action_dim)),
                        -noise_clip, noise_clip)
        next_action_batch = agent.predict_actor_target(s2_batch) + noise
        next_action_batch = np.clip(next_action_batch, -agent.action_bound, agent.action_bound)

        # Calculate targets
        target_Q1, target_Q2 = agent.predict_critic_target(s2_batch, next_action_batch)

        target_q = np.minimum(target_Q1, target_Q2)
        # print('target_q.shape', target_q.shape)
        condition = (t_batch == 1)
        # print(condition)
        target_q[condition] = 0
        # predicted_v_i[condition] = 0
        y_i = np.reshape(r_batch, (int(args['minibatch_size']), 1)) + agent.gamma * np.reshape(
            target_q, (int(args['minibatch_size']), 1))

        # Update the critic given the targets
        agent.train_critic(s_batch, a_batch, np.reshape(y_i, (int(args['minibatch_size']), 1)))

        # print('predicted_q_value', predicted_q_value.shape)

        if ite % int(args['policy_freq']) == 0:
            # Update the actor policy using the sampled gradient
            a_outs = agent.predict_actor(s_batch)
            grads = agent.action_gradients(s_batch, a_outs)
            agent.train_actor(s_batch, grads[0])

            # Update target networks
            agent.update_actor_target_network()
            agent.update_critic_target_network()


# ===========================
#   Agent Training
# ===========================
def train(sess, env, env_test, args, agent):
    # Set up summary Ops
    summary_ops, summary_vars = build_summaries()
    episode_R = []

    sess.run(tf.global_variables_initializer())
    writer = tf.summary.FileWriter(args['summary_dir'], sess.graph)

    # Initialize target network weights
    agent.update_actor_target_network()
    agent.update_critic_target_network()

    # Initialize replay memory
    replay_buffer = ReplayBuffer(int(args['buffer_size']), int(args['random_seed']))

    total_step_cnt = 0
    test_iter = 0
    epi_cnt = 0
    return_test = np.zeros((np.ceil(int(args['total_step_num']) / int(args['sample_step_num'])).astype('int') + 1))

    result_name = 'TD3_' + args['env'] + '_trial_idx_' + str(int(args['trial_idx']))
    action_noise = float(args['action_noise'])
    trained_times_steps = 0
    save_cnt = 1
    policy_ite = 0

    #for i in range(int(args['max_episodes'])):
    while total_step_cnt in range( int(args['total_step_num']) ):

        state = env.reset()

        ep_reward = 0
        ep_ave_max_q = 0
        T_end = False

        for j in range(int(args['max_episode_len'])):

            if args['render_env']:
                    env.render()

            # Added exploration noise
            if total_step_cnt < 1e4:
                action = env.action_space.sample()
            else:
                action = agent.predict_actor(np.reshape(state, (1, agent.state_dim))) #+ actor_noise()
                clipped_noise = np.clip( np.random.normal(0, action_noise, size=env.action_space.shape[0]), -0.5, 0.5 )
                action = (action + clipped_noise).clip(env.action_space.low,env.action_space.high)

            state2, reward, terminal, info = env.step(action[0])

            replay_buffer.add(np.reshape(state, (agent.state_dim,)), np.reshape(action, (agent.action_dim,)), reward,
                              terminal, np.reshape(state2, (agent.state_dim,)))

            if j == int(args['max_episode_len']) - 1:
                T_end = True

            state = state2
            ep_reward += reward

            if total_step_cnt != int(args['total_step_num']) and total_step_cnt > 1e3 and total_step_cnt > policy_ite* int(args['policy_batch_size']):
                update_num = total_step_cnt - trained_times_steps
                trained_times_steps = total_step_cnt
                print('update_num', update_num)
                update_policy(sess, env, env_test, args, agent, replay_buffer, action_noise, update_num)
                policy_ite +=1

            total_step_cnt += 1

            if total_step_cnt >= test_iter * int(args['sample_step_num']) or total_step_cnt == 1:
                print('total_step_cnt', total_step_cnt)
                print('evaluating the deterministic policy...')
                for nn in range(int(args['test_num'])):
                    state_test = env_test.reset()
                    return_epi_test = 0
                    for t_test in range(int(args['max_episode_len'])):
                        action_test = agent.predict_actor(np.reshape(state_test, (1, agent.state_dim)))
                        state_test2, reward_test, terminal_test, info_test = env_test.step(action_test[0])
                        state_test = state_test2
                        return_epi_test = return_epi_test + reward_test
                        if terminal_test:
                            break

                    print('test_iter:{:d}, nn:{:d}, return_epi_test: {:d}'.format(int(test_iter), int(nn),
                                                                                  int(return_epi_test)))
                    return_test[test_iter] = return_test[test_iter] + return_epi_test / float(args['test_num'])

                print('return_test[{:d}] {:d}'.format(int(test_iter), int(return_test[test_iter])))
                test_iter += 1

            if total_step_cnt > int(args['save_model_num']) * save_cnt:
                model_path = "./Model/"
                try:
                    import pathlib
                    pathlib.Path(model_path).mkdir(parents=True, exist_ok=True)
                except:
                    print("A model directory does not exist and cannot be created. The policy models are not saved")

                agent.save_model(iteration=test_iter, expname=result_name, model_path=model_path)
                save_cnt += 1

            if terminal or T_end:
                epi_cnt += 1

                print('| Reward: {:d} | Episode: {:d} | Total step num: {:d} |'.format(int(ep_reward), epi_cnt, total_step_cnt ))
                # episode_R.append(ep_reward)
                break


    return return_test


def main(args):
    for ite in range(int(args['trial_num'])):
        print('Trial Number:', ite)

        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.333)
        config = tf.ConfigProto(gpu_options=gpu_options, log_device_placement=False)

        with tf.Session(config=config) as sess:

            if args['change_seed']:
                #rand_seed = 10 * ite
                rand_seed = np.random.randint(1, 1000, size=1)
            else:
                rand_seed = 0
            env = gym.make(args['env'])

            np.random.seed(int(args['random_seed']) +int(rand_seed))
            tf.set_random_seed(int(args['random_seed']) + int(rand_seed))
            env.seed(int(args['random_seed'])+ int(rand_seed))

            env_test = gym.make(args['env'])
            env_test.seed(int(args['random_seed']) + int(rand_seed))

            state_dim = env.observation_space.shape[0]
            action_dim = env.action_space.shape[0]
            print('action_space.shape', env.action_space.shape)
            print('observation_space.shape', env.observation_space.shape)
            action_bound = env.action_space.high
            # Ensure action bound is symmetric
            #print(env.action_space.high)
            #print(env.action_space.low)
            assert (env.action_space.high[0] == -env.action_space.low[0])

            agent = TD3(sess, env, state_dim, action_dim, action_bound, int(args['minibatch_size']),
                         tau=float(args['tau']),
                         actor_lr=float(args['actor_lr']),
                         critic_lr=float(args['critic_lr']),
                         gamma=float(args['gamma']),
                         hidden_dim=np.asarray(args['hidden_dim']))

            # actor_noise = OrnsteinUhlenbeckActionNoise(mu=np.zeros(action_dim))

            if args['use_gym_monitor']:
                if not args['render_env']:
                    env = wrappers.Monitor(
                        env, args['monitor_dir'], video_callable=False, force=True)
                else:
                    env = wrappers.Monitor(env, args['monitor_dir'], video_callable=lambda episode_id: episode_id%50==0, force=True)

            step_R_i = train(sess, env, env_test, args, agent)

            result_path = "./results/trials/"
            try:
                import pathlib
                pathlib.Path(result_path).mkdir(parents=True, exist_ok=True)
            except:
                print("A result directory does not exist and cannot be created. The trial results are not saved")

            result_filename = args['result_file'] + '_' + args['env'] + '_trial_idx_' +  str(int(args['trial_idx'])) + '.txt'

            if args['overwrite_result'] and ite == 0:
                np.savetxt(result_filename, np.asarray(step_R_i))
            else:
                data = np.loadtxt(result_filename, dtype=float)
                data_new = np.vstack((data, np.asarray(step_R_i)))
                np.savetxt( result_filename, data_new)

            if args['use_gym_monitor']:
                env.monitor.close()




if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='provide arguments for TD3 agent')

    # agent parameters
    parser.add_argument('--actor-lr', help='actor network learning rate', default=0.001)
    parser.add_argument('--critic-lr', help='critic network learning rate', default=0.001)
    parser.add_argument('--gamma', help='discount factor for critic updates', default=0.99)
    parser.add_argument('--tau', help='soft target update parameter', default=0.005)
    parser.add_argument('--buffer-size', help='max size of the replay buffer', default=1000000)
    parser.add_argument('--hidden-dim', help='max size of the hidden layers', default=(400, 300))
    parser.add_argument('--minibatch-size', help='size of minibatch for minibatch-SGD', default=100)
    parser.add_argument('--total-step-num', help='total number of time steps', default=1000000)
    parser.add_argument('--sample-step-num', help='number of time steps for recording the return', default=5000)
    parser.add_argument('--test-num', help='number of episode for recording the return', default=10)
    parser.add_argument('--action-noise', help='parameter of the noise for exploration', default=0.2)
    parser.add_argument('--policy-freq', help='frequency of updating the policy', default=2)
    parser.add_argument('--policy-batch-size', help='batch size for updating policy', default=1000)

    # run parameters
    # parser.add_argument('--env', help='choose the gym env- tested on {Pendulum-v0}', default='Pendulum-v0')
    parser.add_argument('--env', help='choose the gym env- tested on {Pendulum-v0}')
    parser.add_argument('--env-id', type=int, default=6, help='choose the gym env- tested on {Pendulum-v0}')
    parser.add_argument('--random-seed', help='random seed for repeatability', default=1234)
    parser.add_argument('--max-episodes', help='max num of episodes to do while training', default=1001) #50000
    parser.add_argument('--max-episode-len', help='max length of 1 episode', default=1000)
    parser.add_argument('--render-env', help='render the gym env', action='store_true')
    parser.add_argument('--use-gym-monitor', help='record gym results', action='store_true')
    parser.add_argument('--monitor-dir', help='directory for storing gym results', default='./results/gym_td3')
    parser.add_argument('--summary-dir', help='directory for storing tensorboard info', default='./results/tf_td3')
    parser.add_argument('--result-file', help='file name for storing results from multiple trials',
                        default='./results/trials/trials_td3')
    parser.add_argument('--overwrite-result', help='flag for overwriting the trial file', default=True)
    parser.add_argument('--trial-num', help='number of trials', default=1)
    parser.add_argument('--trial-idx', help='index of trials', default=0)
    parser.add_argument('--change-seed', help='change the random seed to obtain different results', default=False)
    parser.add_argument('--save_model-num', help='number of time steps for saving the network models', default=500000)


    parser.set_defaults(render_env=False)
    parser.set_defaults(use_gym_monitor=False)

    parser.set_defaults(change_seed=True)
    parser.set_defaults(overwrite_result=True)

    args_tmp = parser.parse_args()

    if args_tmp.env is None:
        env_dict = {0 : "Pendulum-v0",
                    1 : "InvertedPendulum-v1",
                    2 : "InvertedDoublePendulum-v1",
                    3 : "Reacher-v1",
                    4 : "Swimmer-v1",
                    5 : "Ant-v1",
                    6 : "Hopper-v1",
                    7 : "Walker2d-v1",
                    8 : "HalfCheetah-v1",
                    9 : "Humanoid-v1",
                    10: "HumanoidStandup-v1",
                    11: "MountainCarContinuous-v0"
        }
        args_tmp.env = env_dict[args_tmp.env_id]
    args = vars(args_tmp)

    pp.pprint(args)

    main(args)
